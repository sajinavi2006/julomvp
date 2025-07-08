from __future__ import print_function
from __future__ import division
from builtins import str
from past.utils import old_div
from builtins import object
import logging

from datetime import datetime
from django.db import transaction
from babel.numbers import parse_number
from django.utils import timezone
from django.db.models import Sum
from dateutil.relativedelta import relativedelta

from ..services import process_partial_payment
from ..services import record_payment_transaction
from ..services import reverse_repayment_transaction
from ..models import (PaymentEvent,
                      PaymentMethod,
                      PaymentNote,
                      RepaymentTransaction,
                      Payment,
                      Loan,
                      CustomerCampaignParameter)
from ..utils import display_rupiah
from ..statuses import PaymentStatusCodes
from ..statuses import LoanStatusCodes
from ..statuses import ApplicationStatusCodes
from ..exceptions import JuloException
from ..tasks2.campaign_tasks import send_pn_notify_cashback
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.payback.constants import WaiverConst
from juloserver.julo.constants import WaiveCampaignConst
from juloserver.julo.services import process_received_payment
from juloserver.payback.services.waiver import (waive_interest_paid,
                                                waive_interest_unpaid,
                                                waive_late_fee_paid,
                                                waive_late_fee_unpaid,
                                                waive_principal_paid,
                                                waive_principal_unpaid,
                                                get_remaining_principal,
                                                get_remaining_late_fee,
                                                get_remaining_interest)
from juloserver.payback.services.waiver import process_waiver_before_payment
from juloserver.payback.services.waiver import get_existing_waiver_temp
from juloserver.payback.services.waiver import automate_late_fee_waiver
from juloserver.loan_refinancing.services.loan_related import (
    get_unpaid_payments,
    regenerate_loan_refinancing_offer
)
from juloserver.loan_refinancing.services.refinancing_product_related import (
    get_covid_loan_refinancing_request,
    check_eligibility_of_covid_loan_refinancing,
    CovidLoanRefinancing,
    process_partial_paid_loan_refinancing
)
from juloserver.julo.services import get_grace_period_days
from juloserver.promo.models import WaivePromo
from ...cashback.constants import CashbackChangeReason

logger = logging.getLogger(__name__)


class PaymentEventServices(object):
    COLLECTION_ROLES = (JuloUserRoles.COLLECTION_SUPERVISOR)

    def get_detail(self, payment, user, user_groups):
        list_detail = {
            'payment_events': [],
            'dropdown_event': [],
            'status_event': False
        }

        payment_events = payment.paymentevent_set.all().order_by('-id')
        list_detail['payment_events'] = self.get_status_reverse(payment_events, user_groups)
        list_detail['dropdown_event'] = self.get_dropdown_event(user_groups, payment=payment)
        list_detail['status_event'] = self.get_status_event(payment_events, user, user_groups)
        return list_detail

    def get_status_reverse(self, payment_events, user_groups):
        allowed_roles = (JuloUserRoles.BO_FINANCE, JuloUserRoles.COLLECTION_SUPERVISOR)
        if not any(role in user_groups for role in allowed_roles):
            for payment_event in payment_events:
                payment_event.can_reverse = False
        return payment_events

    def get_dropdown_event(self, user_groups, payment=None):
        dropdown = []
        if type(payment) == list:
            for each in payment:
                if JuloUserRoles.BO_FINANCE in user_groups:
                    dropdown += [{
                        'value': 'payment',
                        'desc': 'Payment'
                    }, {
                        'value': 'late_fee',
                        'desc': 'Late Fee'
                    }, {
                        'value': 'customer_wallet',
                        'desc': 'Customer Wallet'
                    }]
                if JuloUserRoles.COLLECTION_SUPERVISOR in user_groups:
                    if each and each.status not in PaymentStatusCodes.paid_status_codes():
                        dropdown += [
                            {
                                'value': 'waive_late_fee_unpaid',
                                'desc': 'Waive Late Fee Unpaid',
                            }, {
                                'value': 'waive_interest_unpaid',
                                'desc': 'Waive Interest Unpaid'
                            },{
                                'value': 'waive_principal_unpaid',
                                'desc': 'Waive Principal Unpaid'
                            },{
                                'value': 'waive_late_fee_paid',
                                'desc': 'Waive Late Fee Paid'
                            }, {
                                'value': 'waive_interest_paid',
                                'desc': 'Waive Interest Paid'
                            },{
                                'value': 'waive_principal_paid',
                                'desc': 'Waive Principal Paid'
                            }
                        ]
                return dropdown
        else:
            if JuloUserRoles.BO_FINANCE in user_groups:
                dropdown += [{
                    'value': 'payment',
                    'desc': 'Payment'
                }, {
                    'value': 'late_fee',
                    'desc': 'Late Fee'
                }, {
                    'value': 'customer_wallet',
                    'desc': 'Customer Wallet'
                }]
            if JuloUserRoles.COLLECTION_SUPERVISOR in user_groups:
                if payment and payment.status not in PaymentStatusCodes.paid_status_codes():
                    dropdown += [
                        {
                            'value': 'waive_late_fee_unpaid',
                            'desc': 'Waive Late Fee Unpaid',
                        }, {
                            'value': 'waive_interest_unpaid',
                            'desc': 'Waive Interest Unpaid'
                        },{
                            'value': 'waive_principal_unpaid',
                            'desc': 'Waive Principal Unpaid'
                        },{
                            'value': 'waive_late_fee_paid',
                            'desc': 'Waive Late Fee Paid'
                        }, {
                            'value': 'waive_interest_paid',
                            'desc': 'Waive Interest Paid'
                        },{
                            'value': 'waive_principal_paid',
                            'desc': 'Waive Principal Paid'
                        }
                    ]
            return dropdown

    def get_status_event(self, payment_events, user, user_groups):
        if JuloUserRoles.BO_FINANCE in user_groups:
            return True
        elif any(role in self.COLLECTION_ROLES for role in user_groups):
            return True
        elif JuloUserRoles.COLLECTION_AGENT_2 in user_groups:
            already_event = payment_events.filter(added_by_id=user.id)
            if already_event:
                return False
            else:
                return True

    def get_paid_date_from_event_before(self, payment):
        events = payment.paymentevent_set.filter(
            event_type__in=['payment', 'customer_wallet'],
            can_reverse=True
            ).order_by('id')
        try:
            paid_date = events[len(events)-2].event_date if len(events) > 1 else None
        except IndexError:
            paid_date = None

        return paid_date

    def reverse_payment_event(self, payment_event):
        logger.info({
            'action': 'reverse_payment_event',
            'payment_event': payment_event.id
        })
        with transaction.atomic():
            payment_event.can_reverse = False
            payment_event.save()
            payment_event_void = PaymentEvent.objects.create(
                payment=payment_event.payment,
                event_payment=payment_event.event_payment * -1,
                event_due_amount=payment_event.event_due_amount,
                event_date=payment_event.event_date,
                event_type='%s_void' % (payment_event.event_type),
                payment_receipt=payment_event.payment_receipt,
                payment_method=payment_event.payment_method,
                can_reverse=False)
        return payment_event_void

    def process_event_type_payment(
            self, payment, data, reversal_payment_event_id=None, with_waiver=True):
        payment_method = None
        paid_date = data['paid_date']
        notes = data['notes']
        payment_method_id = data['payment_method_id']
        payment_receipt = data['payment_receipt']
        use_credits = data['use_credits']
        partial_payment = parse_number(data['partial_payment'], locale='id_ID')
        use_credits = True if use_credits == "true" else False
        note_template = '[Add Event Payment]\n\
                    amount: %s,\n\
                    paid date : %s,\n\
                    note : %s.\n' % (display_rupiah(partial_payment),
                                     paid_date,
                                     notes)
        if payment_method_id:
            payment_method = PaymentMethod.objects.get_or_none(pk=payment_method_id)
            if not payment_method:
                return False
        logger.info({
            'action': 'process_event_type_payment',
            'payment_id': payment.id,
            'amount': partial_payment,
            'paid_date': paid_date,
            'note': notes,
            'use_credit': use_credits,
        })
        covid_loan_refinancing_request = get_covid_loan_refinancing_request(payment.loan)
        paid_amount_refinancing = partial_payment
        paid_date_refinancing = datetime.strptime(paid_date, "%d-%m-%Y").date()
        if covid_loan_refinancing_request and \
                check_eligibility_of_covid_loan_refinancing(
                    covid_loan_refinancing_request, paid_date_refinancing, partial_payment):
            covid_lf_factory = CovidLoanRefinancing(
                payment, covid_loan_refinancing_request)

            is_covid_loan_refinancing_active = covid_lf_factory.activate()

            if not is_covid_loan_refinancing_active:
                raise JuloException('failed to activate covid loan refinancing',
                                    'gagal aktivasi covid loan refinancing')

            payment = get_unpaid_payments(payment.loan, order_by='payment_number')[0]
            paid_amount_refinancing = process_partial_paid_loan_refinancing(
                covid_loan_refinancing_request,
                payment,
                paid_amount_refinancing
            )

        with transaction.atomic():
            # waive process if exist
            paid_date = datetime.strptime(paid_date, "%d-%m-%Y").date()
            if with_waiver:
                process_waiver_before_payment(payment, partial_payment, paid_date)
            result = process_partial_payment(payment,
                                             paid_amount_refinancing,
                                             note_template,
                                             paid_date=paid_date,
                                             use_wallet=use_credits,
                                             payment_receipt=payment_receipt,
                                             payment_method=payment_method,
                                             reversal_payment_event_id=reversal_payment_event_id)

            check_eligibility_of_waiver_early_payoff_campaign_promo(payment.loan.id)
            regenerate_loan_refinancing_offer(payment.loan)
        return result

    def process_event_type_late_fee(self, payment, data):
        result = False
        payment_paid_status = [
            PaymentStatusCodes.PAID_ON_TIME,
            PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
            PaymentStatusCodes.PAID_LATE,
        ]
        if payment.payment_status.status_code in payment_paid_status:
            return result
        loan = payment.loan
        late_fee_amount = parse_number(data['late_fee_amount'], locale='id_ID')
        late_fee_amount, is_max = loan.get_status_max_late_fee(late_fee_amount)
        if is_max:
            return result
        event_date = datetime.strptime(data['event_date'], "%d-%m-%Y").date()
        due_amount_before = payment.due_amount
        note = '[Add Event Late Fee]\n\
                amount: %s,\n\
                date: %s.' % (display_rupiah(late_fee_amount), data['event_date'])
        logger.info({
            'action': 'process_event_type_late_fee',
            'payment_id': payment.id,
            'late_fee_amount': late_fee_amount,
            'event_date': event_date,
            'due_amount_before': due_amount_before
        })
        try:
            with transaction.atomic():
                # change payment
                payment.due_amount += late_fee_amount
                payment.late_fee_applied += 1
                payment.late_fee_amount += late_fee_amount
                payment.update_status_based_on_due_date()
                payment.save(update_fields=['due_amount',
                                            'late_fee_applied',
                                            'late_fee_amount',
                                            'payment_status',
                                            'udate'])
                # create payment event
                PaymentEvent.objects.create(payment=payment,
                                            event_payment=-late_fee_amount,
                                            event_due_amount=due_amount_before,
                                            event_date=event_date,
                                            event_type='late_fee')
                # create payment note
                PaymentNote.objects.create(
                    note_text=note,
                    payment=payment)

                automate_late_fee_waiver(payment, late_fee_amount, event_date)
                result = True
        except JuloException as e:
            logger.info({
                'action': 'process_event_type_late_fee_error',
                'payment_id': payment.id,
                'message': str(e)
            })
        return result

    def process_event_type_customer_wallet(self, payment, data):
        result = False
        customer = payment.loan.customer
        amount = parse_number(data['use_cashback_amount'], locale='id_ID')
        event_date = data['event_date']
        event_date = datetime.strptime(event_date, "%d-%m-%Y").date()
        old_due_amount = payment.due_amount
        note = '[Add Event Customer Wallet]\n\
                amount : %s.' % (display_rupiah(amount))
        logger.info({
            'action': 'process_event_type_customer_wallet',
            'payment_id': payment.id,
            'amount': amount,
        })
        try:
            with transaction.atomic():
                # change payment
                payment.paid_amount += amount
                payment.due_amount -= amount
                payment.paid_date = event_date
                payment.redeemed_cashback += amount
                payment.save(update_fields=['paid_amount',
                                            'due_amount',
                                            'paid_date',
                                            'redeemed_cashback',
                                            'udate'])
                # change customer wallet
                customer.change_wallet_balance(change_accruing=-amount,
                                               change_available=-amount,
                                               reason='used_on_payment',
                                               payment=payment)
                # create payment event
                PaymentEvent.objects.create(
                    payment=payment,
                    event_payment=amount,
                    event_due_amount=old_due_amount,
                    event_date=event_date,
                    event_type='customer_wallet')
                # save lender transaction
                record_payment_transaction(
                    payment, amount, old_due_amount, event_date, 'borrower_wallet')
                # create payment note
                PaymentNote.objects.create(
                    note_text=note,
                    payment=payment)
                result = True
        except JuloException as e:
            logger.info({
                'action': 'process_event_type_customer_wallet_error',
                'payment_id': payment.id,
                'message': str(e)
            })
        return result

    def waiver_validation(self, waiver_amount, payment, user_groups, waiver_data):
        result = False
        if not any(role in self.COLLECTION_ROLES for role in user_groups):
            message = "Need Supervisor Access"
            return result, message

        if int(waiver_amount) <= 0:
            message = "Waive interest amount tidak boleh 0"
            return result, message

        if payment.payment_status.status_code in PaymentStatusCodes.paid_status_codes():
            message = "Payment Status Error"
            return result, message

        if payment.loan.loan_status.status_code == LoanStatusCodes.RENEGOTIATED:
            message = "Payment Status is Restructured"
            return result, message

        if int(waiver_data['max_payment_number']) < payment.payment_number:
            message = "Maximum Dropdown Payment yang dipilih tidak boleh kurang dari Payment Number saat ini"
            return result, message

        date_message = (
            "Waiver validity period tidak boleh melebihi 40 hari ",
            "dari tanggal input waiver. Mohon masukkan tanggal yang sesuai."
        )
        try:
            waive_validity_date = datetime.strptime(waiver_data['waive_validity_date'], "%d-%m-%Y").date()
        except:
            return result, date_message

        today = timezone.localtime(timezone.now()).date()
        last_day = today + relativedelta(days=39)
        if waive_validity_date < today and waive_validity_date > last_day:
            return result, date_message

        return True, ''


    def process_event_type_waive_late_fee(self, payment, data, user_groups):
        if data['event_type'] == 'waive_late_fee_paid':
            message = (
                'Principal / Interest Installment belum selesai. '
                'Silakan input waiver Principal / waiver Interest terlebih dahulu '
                'sebelum input waiver Late Fee.'
            )
            if (payment.installment_principal - payment.paid_principal) > 0:
                return False, message

            if (payment.installment_interest - payment.paid_interest) > 0:
                return False, message

        waive_late_fee_amount = parse_number(data['waive_late_fee_amount'], locale='id_ID')
        result, message = self.waiver_validation(waive_late_fee_amount, payment, user_groups, data)
        if result is False:
            return result, message

        if data['event_type'] == 'waive_late_fee_unpaid':
            remaining_late_fee = get_remaining_late_fee(payment, is_unpaid=False,
                max_payment_number=int(data['max_payment_number']))
            if int(waive_late_fee_amount) > remaining_late_fee:
                logger.error({
                    'action': 'waive_late_fee_unpaid',
                    'error': 'waive_late_fee_amount more than payment.late_fee_amount',
                    'payment_id': payment.id,
                    'waive_late_fee_amount': waive_late_fee_amount,
                    'remaining late fee': remaining_late_fee,
                })
                message = "Amount tidak boleh melebihi Max waived late fee %s" % display_rupiah(remaining_late_fee)
                return False, message
            waive_validity_date = datetime.strptime(data['waive_validity_date'], "%d-%m-%Y").date()
            result, message = waive_late_fee_unpaid(payment,
                                                    waive_late_fee_amount,
                                                    data['note'],
                                                    data['max_payment_number'],
                                                    waive_validity_date)
        elif data['event_type'] == 'waive_late_fee_paid':
            remaining_late_fee = get_remaining_late_fee(payment, is_unpaid=False)
            if int(waive_late_fee_amount) > remaining_late_fee:
                logger.error({
                    'action': 'waive_late_fee_paid',
                    'error': 'waive_late_fee_amount more than payment.late_fee_amount',
                    'payment_id': payment.id,
                    'waive_late_fee_amount': waive_late_fee_amount,
                    'remaining late fee': remaining_late_fee,
                })
                message = "Amount tidak boleh melebihi Max waived late fee %s" % display_rupiah(remaining_late_fee)
                return False, message
            result, message = waive_late_fee_paid(payment,
                                                  waive_late_fee_amount,
                                                  data['note'])
        else:
            result=False
            message='event_type tidak dikenal'
        return result, message

    def process_event_type_waive_interest(self, payment, data, user_groups):
        if data['event_type'] == 'waive_interest_paid':
            message = (
                'Principal Installment belum selesai. '
                'Silakan input waiver waiver Principal terlebih dahulu '
                'sebelum input waiver Interest.'
            )
            if (payment.installment_principal - payment.paid_principal) > 0:
                return False, message

        waive_interest_amount = parse_number(data['waive_interest_amount'], locale='id_ID')
        result, message = self.waiver_validation(waive_interest_amount, payment, user_groups, data)
        if result is False:
            return result, message

        if data['event_type'] == 'waive_interest_unpaid':
            remaining_interest = get_remaining_interest(payment, is_unpaid=False,
                max_payment_number=int(data['max_payment_number']))
            if int(waive_interest_amount) > remaining_interest:
                logger.error({
                    'action': 'waive_interest_unpaid',
                    'error': 'waive_interest_amount more than loan total_interest ',
                    'payment_id': payment.id,
                    'waive_interest_amount': waive_interest_amount,
                    'loan total interest': remaining_interest,
                })
                message = "Amount tidak boleh melebihi Max waived interest %s" % display_rupiah(remaining_interest)
                return False, message
            waive_validity_date = datetime.strptime(data['waive_validity_date'], "%d-%m-%Y").date()
            result, message = waive_interest_unpaid(payment,
                                                    waive_interest_amount,
                                                    data['note'],
                                                    data['max_payment_number'],
                                                    waive_validity_date)
        elif data['event_type'] == 'waive_interest_paid':
            remaining_interest = get_remaining_interest(payment, is_unpaid=False)

            if int(waive_interest_amount) > remaining_interest:
                logger.error({
                    'action': 'waive_interest_paid',
                    'error': 'waive_interest_amount more than loan total_interest ',
                    'payment_id': payment.id,
                    'waive_interest_amount': waive_interest_amount,
                    'loan total interest': remaining_interest,
                })
                message = "Amount tidak boleh melebihi Max waived interest %s" % display_rupiah(remaining_interest)
                return False, message

            result, message = waive_interest_paid(payment,
                                                  waive_interest_amount,
                                                  data['note'])
        else:
            result = False
            message='event_type tidak dikenal'
        return result, message

    def process_event_type_waive_principal(self, payment, data, user_groups):
        message = (
            'Late Fee Waiver / Interest Waiver belum dimasukkan. '
            'Silakan input waiver Late Fee / waiver Interest terlebih dahulu '
            'sebelum input waiver Principal.'
        )
        if data['event_type'] == 'waive_principal_unpaid':
            existing_waiver_temp = get_existing_waiver_temp(payment)
            if not existing_waiver_temp:
                return False, message

            if existing_waiver_temp:
                need_late_fee = False
                waiver_late_fee = 0
                if existing_waiver_temp.late_fee_waiver_amt:
                    waiver_late_fee = int(existing_waiver_temp.late_fee_waiver_amt)

                if waiver_late_fee == 0 and payment.late_fee_amount > 0:
                    need_late_fee = True

                waiver_interest = 0
                if existing_waiver_temp.interest_waiver_amt:
                    waiver_interest = int(existing_waiver_temp.interest_waiver_amt)

                if need_late_fee or waiver_interest == 0:
                    return False, message

        waive_principal_amount = parse_number(data['waive_principal_amount'], locale='id_ID')
        result, message = self.waiver_validation(waive_principal_amount, payment, user_groups, data)
        if result is False:
            return result, message

        if data['event_type'] == 'waive_principal_unpaid':
            remaining_principal = get_remaining_principal(payment, is_unpaid=False,
                max_payment_number=int(data['max_payment_number']))
            if int(waive_principal_amount) >= remaining_principal:
                logger.error({
                    'action': 'waive_principal_unpaid',
                    'error': 'waive_principal_amount more than equals loan total_principal ',
                    'payment_id': payment.id,
                    'waive_principal_amount': waive_principal_amount,
                    'loan total principal': remaining_principal,
                })
                message = "Jumlah principal waiver melebihi atau sama dengan total principal amount yang belum terbayar. Mohon kurangi jumlah principal waiver yang dimasukkan."
                return False, message
            waive_validity_date = datetime.strptime(data['waive_validity_date'], "%d-%m-%Y").date()
            result, message = waive_principal_unpaid(payment,
                                                    waive_principal_amount,
                                                    data['note'],
                                                    data['max_payment_number'],
                                                    waive_validity_date)
        elif data['event_type'] == 'waive_principal_paid':
            remaining_principal = get_remaining_principal(payment, is_unpaid=False)

            if int(waive_principal_amount) > remaining_principal:
                logger.error({
                    'action': 'waive_principal_paid',
                    'error': 'waive_principal_amount more than loan total_principal ',
                    'payment_id': payment.id,
                    'waive_principal_amount': waive_principal_amount,
                    'loan total principal': remaining_principal,
                })
                message = "Jumlah principal waiver melebihi dengan total principal amount yang belum terbayar. Mohon kurangi jumlah principal waiver yang dimasukkan."
                return False, message
            today = timezone.localtime(timezone.now()).date()
            result, message = waive_principal_paid(payment,
                                                  waive_principal_amount,
                                                  data['note'],
                                                  paid_date=today)
        else:
            result = False
            message='event_type tidak dikenal'
        return result, message

    def process_reversal_event_type_payment(self, payment_event, note):
        result = False
        payment = payment_event.payment
        loan = payment.loan
        customer = loan.customer
        paid_date = self.get_paid_date_from_event_before(payment)
        repayment_transaction = RepaymentTransaction.objects.filter(
            payment=payment,
            due_amount_before=payment_event.event_due_amount,
            repayment_source='borrower_bank'
        ).last()
        payment_method = payment_event.payment_method
        note_payment_method = ''
        note = ',\nnote: %s' % (note)
        if payment_method:
            note_payment_method = ',\n\
                                    payment_method: %s,\n\
                                    payment_receipt: %s' % (payment_method.payment_method_name, payment_event.payment_receipt)
        template_note = '[Reversal Event Payment]\n\
                amount: %s,\n\
                date: %s%s%s.' % (display_rupiah(payment_event.event_payment), payment_event.event_date.strftime("%d-%m-%Y"), note_payment_method, note)
        try:
            with transaction.atomic():
                # update payment and repayment_transaction
                if repayment_transaction:
                    payment.paid_interest -= repayment_transaction.borrower_repaid_interest
                    payment.paid_principal -= repayment_transaction.borrower_repaid_principal
                    payment.paid_late_fee -= repayment_transaction.borrower_repaid_late_fee
                    reverse_repayment_transaction(repayment_transaction, 'borrower_bank_void')
                payment.paid_amount -= payment_event.event_payment
                payment.due_amount += payment_event.event_payment
                payment.paid_date = paid_date
                # reverse cashback
                if payment.cashback_earned:
                    change_available = loan.cashback_earned_total if loan.loan_status.status_code == LoanStatusCodes.PAID_OFF else 0
                    customer.change_wallet_balance(change_accruing=-payment.cashback_earned,
                                                   change_available=-change_available,
                                                   reason='payment_reversal',
                                                   payment=payment)
                    loan.cashback_earned_total -= payment.cashback_earned
                    payment.cashback_earned = 0

                payment.update_status_based_on_due_date()

                payment.save(update_fields=['paid_interest',
                                            'paid_principal',
                                            'paid_late_fee',
                                            'paid_amount',
                                            'due_amount',
                                            'paid_date',
                                            'cashback_earned',
                                            'payment_status',
                                            'udate'])
                # update loan
                loan.update_status()
                loan.save()

                # update can_reapply customer
                customer.can_reapply = False
                customer.save()

                # reverse payment event
                payment_event_void = self.reverse_payment_event(payment_event)
                PaymentNote.objects.create(
                    note_text=template_note,
                    payment=payment)
                result = True
        except JuloException as e:
            logger.info({
                'action': 'process_reversal_event_type_payment_error',
                'payment_event': payment_event.id,
                'message': str(e)
            })
        return result, payment_event_void

    def process_reversal_event_type_late_fee(self, payment_event, note):
        result = False
        payment = payment_event.payment
        note = ',\nnote: %s' % (note)
        template_note = '[Reversal Event Late Fee]\n\
                amount: %s,\n\
                date: %s%s.' % (display_rupiah(payment_event.event_payment), payment_event.event_date.strftime("%d-%m-%Y"), note)
        try:
            with transaction.atomic():
                payment.late_fee_applied = payment.late_fee_applied - 1 if payment.late_fee_applied else 0
                payment.due_amount += payment_event.event_payment
                payment.late_fee_amount += payment_event.event_payment
                payment.update_status_based_on_due_date()
                payment.save(update_fields=['late_fee_applied',
                                            'due_amount',
                                            'late_fee_amount',
                                            'payment_status',
                                            'udate'])
                self.reverse_payment_event(payment_event)
                PaymentNote.objects.create(
                    note_text=template_note,
                    payment=payment)
                result = True
        except JuloException as e:
            logger.info({
                'action': 'process_reversal_event_type_late_fee_error',
                'payment_event': payment_event.id,
                'message': str(e)
            })
        return result

    def process_reversal_event_type_customer_wallet(self, payment_event, note):
        result = False
        payment = payment_event.payment
        loan = payment.loan
        customer = loan.customer
        paid_date = self.get_paid_date_from_event_before(payment)
        repayment_transaction = RepaymentTransaction.objects.filter(
            payment=payment,
            due_amount_before=payment_event.event_due_amount,
            repayment_source='borrower_wallet'
        ).last()
        note = ',\nnote: %s' % (note)
        template_note = '[Reversal Event Customer Wallet]\n\
                amount: %s,\n\
                date : %s%s.' % (display_rupiah(payment_event.event_payment), payment_event.event_date.strftime("%d-%m-%Y"), note)
        try:
            with transaction.atomic():
                # update payment and repayment_transaction
                if repayment_transaction:
                    payment.paid_interest -= repayment_transaction.borrower_repaid_interest
                    payment.paid_principal -= repayment_transaction.borrower_repaid_principal
                    payment.paid_late_fee -= repayment_transaction.borrower_repaid_late_fee
                    reverse_repayment_transaction(repayment_transaction, 'borrower_wallet_void')
                payment.paid_amount -= payment_event.event_payment
                payment.due_amount += payment_event.event_payment
                payment.redeemed_cashback -= payment_event.event_payment
                payment.paid_date = paid_date
                # reverse cashback
                if payment.cashback_earned:
                    change_available = loan.cashback_earned_total if loan.loan_status.status_code == LoanStatusCodes.PAID_OFF else 0
                    customer.change_wallet_balance(change_accruing=-payment.cashback_earned,
                                                   change_available=-change_available,
                                                   reason='payment_reversal',
                                                   payment=payment)
                    loan.cashback_earned_total -= payment.cashback_earned
                    payment.cashback_earned = 0
                payment.update_status_based_on_due_date()
                payment.save(update_fields=['paid_interest',
                                            'paid_principal',
                                            'paid_late_fee',
                                            'paid_amount',
                                            'due_amount',
                                            'redeemed_cashback',
                                            'paid_date',
                                            'cashback_earned',
                                            'payment_status',
                                            'udate'])
                # update loan
                loan.update_status()
                loan.save()
                # refund cashback
                customer.change_wallet_balance(change_accruing=payment_event.event_payment,
                                               change_available=payment_event.event_payment,
                                               reason=CashbackChangeReason.CASHBACK_REVERSAL,
                                               payment=payment)
                # reverse payment event
                self.reverse_payment_event(payment_event)
                PaymentNote.objects.create(
                    note_text=template_note,
                    payment=payment)
                result = True
        except JuloException as e:
            logger.info({
                'action': 'process_reversal_event_type_customer_wallet_error',
                'payment_event': payment_event.id,
                'message': str(e)
            })
        return result

    def process_reversal_event_type_waive_late_fee(self, payment_event, note):
        result = False
        payment = payment_event.payment
        template_note = '[Reversal Event Waive Late Fee]\n\
                amount: %s,\n\
                date: %s,\n\
                note: %s.' % (display_rupiah(payment_event.event_payment), payment_event.event_date.strftime("%d-%m-%Y"), note)
        try:
            with transaction.atomic():
                payment.due_amount += payment_event.event_payment
                payment.paid_amount -= payment_event.event_payment
                if payment.loan.partner:
                    payment.paid_late_fee -= payment_event.event_payment
                payment.save(update_fields=['due_amount',
                                            'paid_amount',
                                            'paid_late_fee',
                                            'udate'])
                self.reverse_payment_event(payment_event)
                PaymentNote.objects.create(
                    note_text=template_note,
                    payment=payment)
                result = True
        except JuloException as e:
            logger.info({
                'action': 'process_reversal_event_type_waive_late_fee_error',
                'payment_event': payment_event.id,
                'message': str(e)
            })
        return result

    def process_transfer_payment_after_reversal(self, origin_event, payment_destination_id, event_void_id):
        payment_destination = Payment.objects.get(pk=payment_destination_id)
        payment_origin = origin_event.payment
        note = 'Reversal from %s with payment_event_id %s with amount %s' % (
            payment_origin.id, origin_event.id, origin_event.event_payment)
        data = {
            'paid_date': origin_event.event_date.strftime("%d-%m-%Y"),
            'notes': note,
            'payment_method_id': origin_event.payment_method_id,
            'payment_receipt': origin_event.payment_receipt,
            'use_credits': 'false',
            'partial_payment': str(origin_event.event_payment),

        }
        self.process_event_type_payment(
            payment_destination, data, reversal_payment_event_id=event_void_id)



def waiver_campaign_promo(loan_id, event_type, campaign_start_date, principal_percentage=100):
    print("waiver_campaign_promo executed with %s" % event_type) #for QA to check the waiver executed
    today = timezone.localtime(timezone.now()).date()
    promo_payments = WaivePromo.objects.filter(loan_id=loan_id)
    total_principal_amount = promo_payments.aggregate(
        total_principal_amount=Sum('remaining_installment_principal')) \
        .get('total_principal_amount')

    promo_payment_ids = promo_payments.values_list('payment', flat=True)
    total_paid_amount = PaymentEvent.objects.filter(payment__in=promo_payment_ids,
                                                    event_type='payment',
                                                    cdate__gte=campaign_start_date) \
        .aggregate(total_paid_amount=Sum('event_payment')) \
        .get('total_paid_amount')

    customer_min_to_paid = old_div(total_principal_amount * principal_percentage, 100)

    if total_paid_amount < customer_min_to_paid:
        return

    for promo_payment in promo_payments:
        payment = Payment.objects.get(pk=promo_payment.payment_id)

        if payment.due_amount <= 0:
            continue

        total_amount = payment.remaining_principal + payment.remaining_interest + payment.remaining_late_fee

        PaymentEvent.objects.create(
            payment=payment,
            event_payment=total_amount,
            event_due_amount=total_amount,
            event_date=today,
            event_type=event_type)

        new_paid_interest = payment.installment_interest
        new_paid_principal = payment.installment_principal
        new_paid_late_fee = payment.late_fee_amount
        new_paid_amount = new_paid_interest + new_paid_principal + new_paid_late_fee
        loan = payment.loan

        payment.update_safely(
            due_amount=0,
            payment_status_id=PaymentStatusCodes.PAID_LATE,
            paid_amount=new_paid_amount,
            paid_interest=new_paid_interest,
            paid_principal=new_paid_principal,
            paid_late_fee=new_paid_late_fee
        )

        loan.update_safely(
            loan_status_id=LoanStatusCodes.PAID_OFF
        )


def waiver_ops_recovery_campaign_promo(loan_id, event_type, campaign_start_date, campaign_end_date):
    promo_payments = WaivePromo.objects.filter(
        loan_id=loan_id,
        promo_event_type=WaiveCampaignConst.OSP_RECOVERY_APR_2020
    ).order_by("payment__payment_number")
    if not promo_payments:
        return
    loan_remaining_amount = promo_payments.aggregate(
        total_principal_amount=Sum('remaining_installment_principal'),
        total_interest_amount=Sum('remaining_installment_interest'),
    )

    customer_min_to_paid = loan_remaining_amount['total_principal_amount'] + \
                           loan_remaining_amount['total_interest_amount']

    promo_payment_ids = promo_payments.values_list('payment', flat=True)
    total_paid_amount = PaymentEvent.objects.filter(payment__in=promo_payment_ids,
                                                    event_type='payment',
                                                    cdate__gte=campaign_start_date,
                                                    cdate__lt=campaign_end_date) \
        .aggregate(total_paid_amount=Sum('event_payment')) \
        .get('total_paid_amount')

    if not total_paid_amount:
        return

    total_waive_late_fee = 0
    cashback_earned_total = 0
    full_installment = False
    if total_paid_amount >= customer_min_to_paid:
        # send cashback
        full_installment = True

    for promo_payment in promo_payments:
        with transaction.atomic():
            payment = promo_payment.payment
            payment.refresh_from_db()

            # calculate waive late fee on each payment
            base_installment_amount = promo_payment.remaining_installment_principal + promo_payment.remaining_installment_interest
            if total_paid_amount >= base_installment_amount:
                total_waive_late_fee += payment.late_fee_amount
                total_paid_amount -= base_installment_amount
                cashback_earned_total += promo_payment.remaining_installment_interest * 0.1 # 10% of remaining principal

            if payment.due_amount <= 0 or total_waive_late_fee <=0:
                continue
            due_amount_before = payment.due_amount

            waive_late_fee_amount = total_waive_late_fee
            if payment.due_amount < total_waive_late_fee:
                waive_late_fee_amount = payment.due_amount

            total_waive_late_fee -= waive_late_fee_amount

            payment.due_amount -= waive_late_fee_amount
            payment.paid_amount += waive_late_fee_amount
            payment.save(update_fields=['due_amount',
                                        'paid_amount',
                                        'udate'])

            event_date = timezone.localtime(timezone.now()).date()
            payment_event = PaymentEvent.objects.create(payment=payment,
                                                        event_payment=waive_late_fee_amount,
                                                        event_due_amount=due_amount_before,
                                                        event_date=event_date,
                                                        event_type=event_type)

            payment_event.update_safely(can_reverse=False)
            if payment.due_amount == 0:  # change payment status to paid
                process_received_payment(payment)

    if full_installment:
        cashback_earned_total = loan_remaining_amount['total_interest_amount'] * 0.4 # 40% of remaining interest

    cashback_earned_total = int(cashback_earned_total)

    if not cashback_earned_total:
        return

    loan = Loan.objects.get(pk=loan_id)
    loan.customer.change_wallet_balance(change_accruing=cashback_earned_total,
                                        change_available=cashback_earned_total,
                                        reason='OSP Recovery Campaign Apr2020',
                                        payment=payment)
    send_pn_notify_cashback.delay(loan.application_id, cashback_earned_total)
    return cashback_earned_total


def waiver_early_payoff_campaign_promo(loan_id, start_promo):
    loan = Loan.objects.filter(pk=loan_id).all_active_mtl().last()
    if not loan:
        return
    today = timezone.localtime(timezone.now()).date()
    promo_payments = WaivePromo.objects.filter(
        loan_id=loan_id,
        promo_event_type=WaiveCampaignConst.RISKY_CUSTOMER_EARLY_PAYOFF
    ).order_by("payment__payment_number")
    if not promo_payments:
        return
    loan_remaining_amount = promo_payments.aggregate(
        total_principal_amount=Sum('remaining_installment_principal'),
        total_interest_amount=Sum('remaining_installment_interest'),
        total_late_fee_amount=Sum('remaining_late_fee'),
    )

    customer_min_to_paid = loan_remaining_amount['total_principal_amount'] + \
                           (old_div((loan_remaining_amount['total_interest_amount'] * 70), 100))
    end_promo = today + relativedelta(days=10)
    promo_payment_ids = promo_payments.values_list('payment', flat=True)
    total_paid_amount = PaymentEvent.objects.filter(payment__in=promo_payment_ids,
                                                    event_type__in=(
                                                        'payment',
                                                        'waive_principal',
                                                        'waive_interest',
                                                        'waive_late_fee',
                                                        'customer_wallet'),
                                                    event_date__gte=start_promo,
                                                    event_date__lte=end_promo) \
        .aggregate(total_paid_amount=Sum('event_payment')) \
        .get('total_paid_amount')
    total_paid_reverse = PaymentEvent.objects.filter(payment__in=promo_payment_ids,
                                                     event_type__in=(
                                                         'payment_void',
                                                         'waive_late_fee_void',
                                                         'waive_interest_void'),
                                                     event_date__gte=start_promo,
                                                     event_date__lte=end_promo) \
        .aggregate(total_paid_amount=Sum('event_payment')) \
        .get('total_paid_amount')

    if total_paid_reverse and total_paid_amount:
        total_paid_amount = total_paid_amount - abs(total_paid_reverse)

    if (total_paid_amount or 0) < customer_min_to_paid:
        return

    total_amount = 0
    updated_payments = []
    for promo_payment in promo_payments:
        payment = Payment.objects.get(pk=promo_payment.payment_id)

        if payment.due_amount <= 0:
            continue

        total_amount += payment.due_amount

        new_paid_interest = payment.installment_interest
        new_paid_principal = payment.installment_principal
        new_paid_late_fee = payment.late_fee_amount
        new_paid_amount = new_paid_interest + new_paid_principal + new_paid_late_fee
        paid_late_days = payment.paid_late_days
        if paid_late_days <= 0:
            new_status = PaymentStatusCodes.PAID_ON_TIME
        elif paid_late_days < get_grace_period_days(payment):
            new_status = PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD
        else:
            new_status = PaymentStatusCodes.PAID_LATE

        payment.update_safely(
            due_amount=0,
            payment_status_id=new_status,
            paid_amount=new_paid_amount,
            paid_interest=new_paid_interest,
            paid_principal=new_paid_principal,
            paid_late_fee=new_paid_late_fee
        )

        updated_payments.append(payment)

    loan.update_status()
    loan.save()

    installment_interest_amount = loan_remaining_amount['total_interest_amount'] * 0.3
    waive_interest_payment_events, waive_late_fee_payment_events = [], []

    for updated_payment in updated_payments:
        waive_interest_payment_events.append(
            PaymentEvent(
                payment=updated_payment,
                event_payment=installment_interest_amount,
                event_due_amount=total_amount,
                event_date=today,
                event_type='promo waive interest',
            )
        )

        if loan_remaining_amount['total_late_fee_amount'] > 0:
            waive_late_fee_payment_events.append(
                PaymentEvent(
                    payment=updated_payment,
                    event_payment=loan_remaining_amount['total_late_fee_amount'],
                    event_due_amount=total_amount - installment_interest_amount,
                    event_date=today,
                    event_type='promo waive late fee',
                )
            )

    PaymentEvent.objects.bulk_create(waive_interest_payment_events + waive_late_fee_payment_events)


def check_eligibility_of_waiver_early_payoff_campaign_promo(loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        return
    today = timezone.localtime(timezone.now()).date()
    today_minus_10 = today - relativedelta(days=10)
    customer_campaign_parameter = CustomerCampaignParameter.objects.filter(
        customer=loan.customer,
        campaign_setting__campaign_name=WaiveCampaignConst.RISKY_CUSTOMER_EARLY_PAYOFF,
        effective_date__gte=today_minus_10,
        effective_date__lte=today
    ).last()
    if customer_campaign_parameter:
        waiver_early_payoff_campaign_promo(loan.id, customer_campaign_parameter.effective_date)

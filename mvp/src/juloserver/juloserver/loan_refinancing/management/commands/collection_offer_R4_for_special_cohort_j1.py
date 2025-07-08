from __future__ import division
from builtins import str
import logging
import sys
import csv
import math
from django.utils import timezone, dateparse
from django.core.management.base import BaseCommand
from django.db import transaction

from juloserver.account.models import Account
from juloserver.account_payment.services.account_payment_related import (
    get_unpaid_account_payment,
    update_checkout_experience_status_to_cancel
)
from juloserver.integapiv1.tasks import update_va_bni_transaction
from juloserver.julo.banks import BankCodes
from juloserver.julo.models import Payment
from juloserver.loan_refinancing.models import (
    LoanRefinancingRequest, LoanRefinancingOffer, LoanRefinancingRequestCampaign,
    WaiverRequest, WaiverPaymentRequest)
from juloserver.julocore.python2.utils import py2round
from juloserver.loan_refinancing.constants import CovidRefinancingConst, Campaign
from django.db.models import Sum, F
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.loan_refinancing.services.notification_related import CovidLoanRefinancingEmail, \
    CovidLoanRefinancingSMS, CovidLoanRefinancingPN
from juloserver.loan_refinancing.utils import get_partner_product
from juloserver.payback.models import WaiverTemp, WaiverPaymentTemp
from juloserver.waiver.models import WaiverAccountPaymentRequest
from juloserver.waiver.services.waiver_related import (
    generate_and_calculate_waiver_request_reactive,
    construct_waiver_request_data_for_cohort_campaign
)
from juloserver.loan_refinancing.services.offer_related import pass_check_refinancing_max_cap_rule_by_account_id

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('-f', '--file', type=str, help='Define file name')

    def handle(self, **options):
        path = options['file']
        with open(path, 'r') as csvfile:
            csv_rows = csv.DictReader(csvfile, delimiter=',')
            rows = [r for r in csv_rows]

        for refinancing_data in rows:
            errors = {
                'email_sent': False,
                'notifications_sent': False,
                'sms_sent': False
            }
            loan_refinancing_request = None
            waiver_request_id = None
            try:
                with transaction.atomic():
                    account = Account.objects.get(id=refinancing_data['account_id'])
                    validate_condition(account)
                    # change the ongoing refinancing request of  Email Sent, Form Viewed,
                    # Offer Generated to Expired
                    LoanRefinancingRequest.objects.filter(
                        account=account, status__in=['Email Sent', 'Form Viewed', 'Offer Generated']
                    ).update(
                        expire_in_days=0,
                        status=CovidRefinancingConst.STATUSES.expired,
                        udate=timezone.localtime(timezone.now())
                    )
                    # update checkout to cancel
                    update_checkout_experience_status_to_cancel(account.id)
                    # create loan refinance request
                    app = account.last_application
                    new_net_income = app.monthly_income - app.monthly_expenses
                    previous_net_income = app.monthly_income - app.monthly_expenses
                    # handle zero division error
                    if new_net_income == 0 or previous_net_income == 0:
                        new_affordability = float(1)
                    else:
                        new_affordability = float(new_net_income) / float(previous_net_income)
                    expire_in_days = (dateparse.parse_date(
                        refinancing_data['expired_at']) - timezone.localtime(timezone.now()).date()).days

                    waiver_request_id, waiver_offer_data = generate_waiver_offer(
                        account, refinancing_data, expire_in_days, refinancing_data['expired_at'],
                        product_line_code=app.product_line_code
                    )
                    # check the prerequisite amount
                    vallidate_prerequisite_amount(waiver_offer_data['prerequisite_amount'])
                    loan_refinancing_request_dict = dict(
                        account_id=refinancing_data['account_id'],
                        affordability_value=new_affordability,
                        product_type='R4',
                        expire_in_days=expire_in_days,
                        loan_duration=0,
                        new_income=0,
                        new_expense=0,
                        status=CovidRefinancingConst.STATUSES.approved,
                        request_date=timezone.localtime(timezone.now()).date(),
                        form_submitted_ts=timezone.localtime(timezone.now()),
                        channel=CovidRefinancingConst.CHANNELS.reactive,
                        comms_channel_1=CovidRefinancingConst.COMMS_CHANNELS.email,
                        comms_channel_2=CovidRefinancingConst.COMMS_CHANNELS.pn,
                        # FOR 'independence day campaign' not send SMS
                        # comms_channel_3=CovidRefinancingConst.COMMS_CHANNELS.sms,
                        prerequisite_amount=waiver_offer_data['prerequisite_amount'],
                        total_latefee_discount=waiver_offer_data['total_latefee_discount']
                    )
                    loan_refinancing_request = LoanRefinancingRequest.objects. \
                        create(**loan_refinancing_request_dict)

                    # create loan refinance offer
                    LoanRefinancingOffer.objects.create(
                        loan_refinancing_request=loan_refinancing_request,
                        **waiver_offer_data
                    )
                    update_va_bni_transaction.delay(
                        account.id,
                        'management.commands.collection_offer_R4_for_special_cohort_j1',
                        waiver_offer_data['prerequisite_amount']
                    )

            except (
                NotEligibleLoanStatus,
                RefinancingRequestOnGoingStatus,
                ZeroPrerequisiteAmount,
                MaxCapRule,
            ) as error:
                errors['reason'] = str(error)
                self.stdout.write(self.style.ERROR(str(error)))
            except Exception as error:
                errors['reason'] = str(error)
                self.stdout.write(self.style.ERROR(str(error)))
                sentry_client = get_julo_sentry_client()
                sentry_client.captureException()
            finally:
                if not errors.get('reason'):
                    status = 'Success'
                    extra_data = None
                else:
                    status = 'Failed'
                    extra_data = errors
                    loan_refinancing_request = None
                    waiver_request_id = None
                # connecting waiver_request with loan_refinancing_request
                WaiverRequest.objects.filter(
                    pk=waiver_request_id
                ).update(
                     loan_refinancing_request=loan_refinancing_request
                )
                # create Historical of Special R4
                loan_ref_req_campaign = LoanRefinancingRequestCampaign.objects.create(
                    loan_refinancing_request=loan_refinancing_request,
                    account_id=refinancing_data['account_id'],
                    campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
                    expired_at=refinancing_data['expired_at'],
                    principal_waiver=refinancing_data['principal_waiver'],
                    interest_waiver=refinancing_data['interest_waiver'],
                    late_fee_waiver=refinancing_data['late_fee_waiver'],
                    offer=refinancing_data['offer'],
                    status=status,
                    extra_data=extra_data
                )

            try:
                if not errors.get('reason'):
                    # send email, sms, pn
                    loan_refinancing_email = CovidLoanRefinancingEmail(loan_refinancing_request)
                    loan_refinancing_email.send_approved_email()
                    errors['email_sent'] = True
                    loan_refinancing_pn = CovidLoanRefinancingPN(loan_refinancing_request)
                    loan_refinancing_pn.send_approved_pn()
                    errors['notifications_sent'] = True
                    # FOR 'independence day campaign' not send SMS
                    # loan_refinancing_sms = CovidLoanRefinancingSMS(loan_refinancing_request)
                    # loan_refinancing_sms.send_approved_sms()
                    # errors['sms_sent'] = True
                    self.stdout.write(
                        self.style.SUCCESS(f"Success created for account id {refinancing_data['account_id']}"))
            except Exception as error:
                self.stdout.write(self.style.ERROR(str(error)))
                self.stdout.write(self.style.ERROR(str(error)))
                sentry_client = get_julo_sentry_client()
                sentry_client.captureException()
                errors['reason'] = str(error)
                loan_ref_req_campaign.update_safely(
                    extra_data=errors
                )


def generate_waiver_offer(account, waivers, validity_in_days, expired_at, product_line_code):
    unpaid_account_payments = get_unpaid_account_payment(account.id)
    installment_count = waivers.get('installment_count', '')
    if installment_count and installment_count.isdigit():
        installment_count = int(installment_count)
        if installment_count > unpaid_account_payments.count():
            raise InstallmentOutOfRange('installment_count is out of range')
        unpaid_account_payments = (
            unpaid_account_payments[:installment_count]
            if installment_count
            else unpaid_account_payments
        )
    waiver_request_data = construct_waiver_request_data_for_cohort_campaign(
        unpaid_account_payments, account, waivers, expired_at, product_line_code, program_name = waivers["offer"]
    )
    waiver_request_obj = WaiverRequest.objects.create(**waiver_request_data)
    selected_waived_account_payments = []
    for account_payment in unpaid_account_payments:
        account_payment_dict = dict(
            account_payment_id=account_payment.id
        )
        selected_waived_account_payments.append(account_payment_dict)
    (
        waiver_payment_request_data,
        waiver_account_payment_request_data,
    ) = generate_and_calculate_waiver_request_reactive(
        waiver_request_data,
        waiver_request_obj,
        selected_waived_account_payments,
        is_from_agent=False,
        is_from_campaign=True,
    )
    if waiver_payment_request_data:
        WaiverPaymentRequest.objects.bulk_create(waiver_payment_request_data)
    if waiver_account_payment_request_data:
        WaiverAccountPaymentRequest.objects.bulk_create(waiver_account_payment_request_data)
    # get fixed late_fee, interest, principal waiver refer from waiver_account_payement_request
    fix_late_fee_waiver = 0
    fix_interest_waiver = 0
    fix_principal_waiver = 0
    fix_total_waiver = 0
    for waiver_account_payment in waiver_account_payment_request_data:
        fix_late_fee_waiver += waiver_account_payment.requested_late_fee_waiver_amount
        fix_interest_waiver += waiver_account_payment.requested_interest_waiver_amount
        fix_principal_waiver += waiver_account_payment.requested_principal_waiver_amount
        fix_total_waiver += waiver_account_payment.total_requested_waiver_amount
    # update waiver_request depend fixed amount
    # fix value waiver_request.requested_waiver_amount
    WaiverRequest.objects.filter(
        pk=waiver_request_obj.id
    ).update(
        requested_late_fee_waiver_amount=fix_late_fee_waiver,
        requested_interest_waiver_amount=fix_interest_waiver,
        requested_principal_waiver_amount=fix_principal_waiver,
        ptp_amount=waiver_request_data['outstanding_amount'] - fix_total_waiver,
        requested_waiver_amount=fix_total_waiver
    )
    waiver_temp = WaiverTemp.objects.create(
        account=account,
        late_fee_waiver_amt=fix_late_fee_waiver,
        interest_waiver_amt=fix_interest_waiver,
        principal_waiver_amt=fix_principal_waiver,
        need_to_pay=waiver_request_data['outstanding_amount'] - fix_total_waiver,
        waiver_date=timezone.now().date(),
        late_fee_waiver_note="Loan Refinancing Reactive",
        interest_waiver_note="Loan Refinancing Reactive",
        principal_waiver_note="Loan Refinancing Reactive",
        valid_until=dateparse.parse_date(expired_at),
        is_automated=True,
        waiver_request=waiver_request_obj,
    )
    # waiver_payment_temp defend waiver_account_payement_request
    waiver_payment_temp_data = []
    for waiver_account_payment in waiver_account_payment_request_data:
        waiver_payment_temp_data.append(
            WaiverPaymentTemp(
                waiver_temp=waiver_temp,
                account_payment_id=waiver_account_payment.account_payment_id,
                late_fee_waiver_amount=waiver_account_payment.requested_late_fee_waiver_amount,
                interest_waiver_amount=waiver_account_payment.requested_interest_waiver_amount,
                principal_waiver_amount=waiver_account_payment.requested_principal_waiver_amount,
            )
        )
    WaiverPaymentTemp.objects.bulk_create(waiver_payment_temp_data)
    return waiver_request_obj.id, dict(
        product_type="R4",
        prerequisite_amount=waiver_request_data['outstanding_amount'] - fix_total_waiver,
        total_latefee_discount=fix_late_fee_waiver,
        total_interest_discount=fix_interest_waiver,
        total_principal_discount=fix_principal_waiver,
        validity_in_days=validity_in_days,
        interest_discount_percentage=str(waivers['interest_waiver']) + '%',
        principal_discount_percentage=str(waivers['principal_waiver']) + '%',
        latefee_discount_percentage=str(waivers['late_fee_waiver']) + '%',
        is_proactive_offer=True,
        is_latest=True,
        is_accepted=True,
        offer_accepted_ts=timezone.localtime(timezone.now())
    )


def validate_condition(account):
    # if account.ever_entered_B5:
    #     raise EverEnteredB5('Account detected ever entered B5')
    if not account.get_all_active_loan():
        raise NotEligibleLoanStatus('Invalid doesnt have active loan')
    invalid_loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        account=account, status__in=CovidRefinancingConst.REACTIVE_OFFER_STATUS_SELECTED_OR_APPROVED
    ).values('id')
    if invalid_loan_refinancing_request:
        raise RefinancingRequestOnGoingStatus('Invalid loan refinancing request status')
    is_passed, err_msg = pass_check_refinancing_max_cap_rule_by_account_id(account.id, 'R4')
    if not is_passed:
        raise MaxCapRule(err_msg)


def validate_lender(lender_list, allowed_lender=[]):
    if not allowed_lender:
        return

    not_allowed_lender = set(lender_list) - set(allowed_lender)
    if not_allowed_lender:
        raise InvalidLender('Found not allowed lender')


def validate_dpd(dpd, dpd_start, dpd_end):
    # dpd_start and dpd_end are allowed inclusively

    # range: -~ until dpd_end
    if not isinstance(dpd_start, int):
        if dpd > dpd_end:
            raise InvalidDpd('DPD outside allowed range')
        else:
            return

    # range: dpd_start until ~
    if not isinstance(dpd_end, int):
        if dpd < dpd_start:
            raise InvalidDpd('DPD outside allowed range')
        else:
            return

    # range: dpd_start until dpd_end
    if (dpd < dpd_start) or (dpd > dpd_end):
        raise InvalidDpd('DPD outside allowed range')


def vallidate_prerequisite_amount(amount):
    if amount <= 0:
        raise ZeroPrerequisiteAmount('This offer have zero value prerequisite amount')


def validate_expire_date(expire_at_date):
    now = timezone.localtime(timezone.now()).date()
    if expire_at_date < now:
        raise InvalidExpireDate('Invalid expire at value')


class NotEligibleLoanStatus(Exception):
    pass


class RefinancingRequestOnGoingStatus(Exception):
    pass


class EverEnteredB5(Exception):
    pass


class ZeroPrerequisiteAmount(Exception):
    pass


class MaxCapRule(Exception):
    pass


class InvalidExpireDate(Exception):
    pass


class InvalidLender(Exception):
    pass


class InvalidDpd(Exception):
    pass


class InstallmentOutOfRange(Exception):
    pass

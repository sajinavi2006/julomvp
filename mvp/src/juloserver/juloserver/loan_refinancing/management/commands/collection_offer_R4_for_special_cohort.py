from __future__ import division
from builtins import str
import logging
import sys
import csv
from django.utils import timezone, dateparse
from django.core.management.base import BaseCommand
from django.db import transaction
from juloserver.julo.models import Loan, Payment
from juloserver.loan_refinancing.models import (
    LoanRefinancingRequest, LoanRefinancingOffer, LoanRefinancingRequestCampaign,
    WaiverRequest, WaiverPaymentRequest)
from juloserver.julocore.python2.utils import py2round
from juloserver.loan_refinancing.constants import CovidRefinancingConst, Campaign
from juloserver.payback.services.waiver import get_remaining_late_fee
from juloserver.payback.services.waiver import get_remaining_interest
from juloserver.payback.services.waiver import get_remaining_principal
from juloserver.loan_refinancing.services.notification_related import (
    CovidLoanRefinancingEmail, CovidLoanRefinancingPN, CovidLoanRefinancingSMS)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.payback.models import WaiverTemp, WaiverPaymentTemp
from juloserver.apiv2.models import LoanRefinancingScore
from juloserver.loan_refinancing.services.loan_related import get_unpaid_payments

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))

eligible_loan_status = [220, 230, 231, 232, 233, 234, 235, 236, 237]


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
            try:
                with transaction.atomic():
                    loan = Loan.objects.get(id=refinancing_data['loan_id'])
                    validate_condition(loan)
                    # change the ongoing refinancing request of  Email Sent, Form Viewed,
                    # Offer Generated to Expired
                    ongoing_loan_refinancing_requests = LoanRefinancingRequest.objects.filter(
                        loan=loan, status__in=['Email Sent', 'Form Viewed', 'Offer Generated']
                    )
                    for request in ongoing_loan_refinancing_requests:
                        request.update_safely(
                            expire_in_days=0,
                            status=CovidRefinancingConst.STATUSES.expired)

                    # create loan refinance request
                    app = loan.application
                    new_net_income = app.monthly_income - app.monthly_expenses
                    previous_net_income = app.monthly_income - app.monthly_expenses
                    new_affordability = float(new_net_income) / float(previous_net_income)
                    expire_in_days = (dateparse.parse_date(
                        refinancing_data['expired_at']) - timezone.now().date()).days
                    waiver_offer_data = generate_waiver_offer(
                        loan, refinancing_data, expire_in_days, refinancing_data['expired_at'])
                    loan_refinancing_request_dict = dict(
                        loan_id=refinancing_data['loan_id'],
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
                        comms_channel_2=CovidRefinancingConst.COMMS_CHANNELS.sms,
                        comms_channel_3=CovidRefinancingConst.COMMS_CHANNELS.pn,
                        prerequisite_amount=waiver_offer_data['prerequisite_amount']
                    )
                    loan_refinancing_request = LoanRefinancingRequest.objects. \
                        create(**loan_refinancing_request_dict)

                    # create loan refinance offer
                    LoanRefinancingOffer.objects.create(
                        loan_refinancing_request=loan_refinancing_request,
                        **waiver_offer_data
                    )

            except (NotEligibleLoanStatus, RefinancingRequestOnGoingStatus) as error:
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
                # create Historical of Special R4
                loan_ref_req_campaign = LoanRefinancingRequestCampaign.objects.create(
                    loan_refinancing_request=loan_refinancing_request,
                    loan_id=refinancing_data['loan_id'],
                    campaign_name=Campaign.R4_SPECIAL_FEB_MAR_20,
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
                    loan_refinancing_sms = CovidLoanRefinancingSMS(loan_refinancing_request)
                    loan_refinancing_sms.send_approved_sms()
                    errors['sms_sent'] = True
                    loan_refinancing_pn = CovidLoanRefinancingPN(loan_refinancing_request)
                    loan_refinancing_pn.send_approved_pn()
                    errors['notifications_sent'] = True
            except Exception as error:
                self.stdout.write(self.style.ERROR(str(error)))
                sentry_client = get_julo_sentry_client()
                sentry_client.captureException()
                errors['reason'] = str(error)
                loan_ref_req_campaign.update_safely(
                    extra_data=errors
                )


def generate_waiver_offer(loan, waivers, validity_in_days, expired_at):
    payments = Payment.objects.filter(
        loan=loan).not_paid_active().order_by('payment_number')
    last_payment = payments.last()
    last_payment_number = last_payment.payment_number
    remaining_late_fee = get_remaining_late_fee(last_payment, True,
                                                max_payment_number=last_payment_number)
    remaining_interest = get_remaining_interest(last_payment, True,
                                                max_payment_number=last_payment_number)
    remaining_principal = get_remaining_principal(last_payment, True,
                                                  max_payment_number=last_payment_number)
    total_unpaid = remaining_late_fee + remaining_interest + remaining_principal

    total_latefee_discount = py2round(
        float(waivers['late_fee_waiver']) * remaining_late_fee // 100)
    total_interest_discount = py2round(
        float(waivers['interest_waiver']) * remaining_interest // 100)
    total_principal_discount = py2round(
        float(waivers['principal_waiver']) * remaining_principal // 100)
    total_discount = total_latefee_discount + total_interest_discount + total_principal_discount

    bucket_name = None
    loan_refinancing_score = LoanRefinancingScore.objects.filter(loan=loan).last()
    if loan_refinancing_score:
        bucket_name = loan_refinancing_score.bucket
    else:
        unpaid_payments = get_unpaid_payments(loan, order_by='payment_number')
        payment = unpaid_payments.first()
        bucket_name = 'Bucket {}'.format(payment.bucket_number)

    waiver_request = WaiverRequest.objects.create(
        loan=loan,
        is_covid_risky=True,
        bucket_name=bucket_name,
        outstanding_amount=total_unpaid,
        unpaid_principal=remaining_principal,
        unpaid_interest=remaining_interest,
        unpaid_late_fee=remaining_late_fee,
        requested_late_fee_waiver_percentage=str(waivers['late_fee_waiver']) + '%',
        requested_late_fee_waiver_amount=total_latefee_discount,
        requested_interest_waiver_percentage=str(waivers['interest_waiver']) + '%',
        requested_interest_waiver_amount=total_interest_discount,
        requested_principal_waiver_percentage=str(waivers['principal_waiver']) + '%',
        requested_principal_waiver_amount=total_principal_discount,
        waiver_validity_date=dateparse.parse_date(expired_at),
        ptp_amount=total_unpaid - total_discount,
        last_payment_number=last_payment_number,
        is_automated=True,
        program_name="r4",
        first_waived_payment=payments.first(),
        last_waived_payment=payments.last(),
        waived_payment_count=payments.count(),
        remaining_amount_for_waived_payment=0,
    )
    waiver_payment_request_data = []
    for payment in payments:
        late_fee = py2round(
            (float(waivers['late_fee_waiver']) / float(100)) * float(
                payment.late_fee_amount))
        interest = py2round(
            (float(waivers['interest_waiver']) / float(100)) * float(
                payment.installment_interest))
        principal = py2round(
            (float(waivers['principal_waiver']) / float(100)) * float(
                payment.installment_principal))
        total = late_fee + interest + principal
        waiver_payment_request_data.append(
            WaiverPaymentRequest(
                waiver_request=waiver_request,
                payment=payment,
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
                is_paid_off_after_ptp=True,
            )
        )
    WaiverPaymentRequest.objects.bulk_create(waiver_payment_request_data)

    waiver_temp = WaiverTemp.objects.create(
        loan=loan,
        late_fee_waiver_amt=total_latefee_discount,
        interest_waiver_amt=total_interest_discount,
        principal_waiver_amt=total_principal_discount,
        need_to_pay=total_unpaid - total_discount,
        waiver_date=timezone.now().date(),
        late_fee_waiver_note="Loan Refinancing Reactive",
        interest_waiver_note="Loan Refinancing Reactive",
        principal_waiver_note="Loan Refinancing Reactive",
        valid_until=dateparse.parse_date(expired_at),
        is_automated=True,
    )
    waiver_payment_temp_data = []
    for payment in payments:
        waiver_payment_temp_data.append(
            WaiverPaymentTemp(
                waiver_temp=waiver_temp,
                payment=payment,
                late_fee_waiver_amount=py2round(
                    (float(waivers['late_fee_waiver']) / float(100)) * float(
                        payment.late_fee_amount)),
                interest_waiver_amount=py2round(
                    (float(waivers['interest_waiver']) / float(100)) * float(
                        payment.installment_interest)),
                principal_waiver_amount=py2round(
                    (float(waivers['principal_waiver']) / float(100)) * float(
                        payment.installment_principal)),
            )
        )
    WaiverPaymentTemp.objects.bulk_create(waiver_payment_temp_data)

    return dict(
        product_type="R4",
        prerequisite_amount=total_unpaid - total_discount,
        total_latefee_discount=total_latefee_discount,
        total_interest_discount=total_interest_discount,
        total_principal_discount=total_principal_discount,
        validity_in_days=validity_in_days,
        interest_discount_percentage=str(waivers['interest_waiver']) + '%',
        principal_discount_percentage=str(waivers['principal_waiver']) + '%',
        latefee_discount_percentage=str(waivers['late_fee_waiver']) + '%',
        is_proactive_offer=True,
        is_latest=True,
        is_accepted=True,
        offer_accepted_ts=timezone.localtime(timezone.now())
    )


def validate_condition(loan):
    if loan.loan_status_id not in eligible_loan_status:
        raise NotEligibleLoanStatus('Invalid loan status code {}'.format(loan.loan_status_id))
    invalid_loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        loan=loan, status__in=['Offer Selected', 'Approved']
    ).values('id')
    if invalid_loan_refinancing_request:
        raise RefinancingRequestOnGoingStatus('Invalid loan refinancing request status')


class NotEligibleLoanStatus(Exception):
    pass


class RefinancingRequestOnGoingStatus(Exception):
    pass

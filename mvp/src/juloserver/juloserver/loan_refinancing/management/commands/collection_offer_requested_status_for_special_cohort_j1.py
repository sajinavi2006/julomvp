import csv
import datetime
from itertools import product
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone, dateparse
from juloserver.account.models import Account
from juloserver.integapiv1.tasks import update_va_bni_transaction
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.loan_refinancing.models import LoanRefinancingRequest, LoanRefinancingRequestCampaign
from juloserver.loan_refinancing.constants import (
    Campaign,
    CovidRefinancingConst
)
from juloserver.loan_refinancing.services.notification_related import (
    CovidLoanRefinancingEmail,
    CovidLoanRefinancingPN
)
from juloserver.account_payment.services.account_payment_related import \
    update_checkout_experience_status_to_cancel


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('-f', '--file', type=str, help='Define file name')

    def handle(self, **options):
        path = options['file']
        with open(path, 'r') as csvfile:
            csv_rows = csv.DictReader(csvfile, delimiter=',')
            rows  = [r for r in csv_rows]

        for refinancing_data in rows:
            errors = {
                'email_sent': False,
                'notifications_sent': False
            }
            loan_refinancing_request = None
            try:
                with transaction.atomic():
                    account = Account.objects.get(id=refinancing_data['account_id'])
                    validation_condition(account)
                    change_following_process_status_to_expired(account)
                    # update checkout to cancel
                    update_checkout_experience_status_to_cancel(account.id)

                    expire_in_days = (dateparse.parse_date(
                        refinancing_data['expired_at']) - timezone.localtime(timezone.now()).date()).days
                    loan_refinancing_request_dict = dict(
                        account_id=refinancing_data['account_id'],
                        expire_in_days=expire_in_days,
                        loan_duration=0,
                        new_income=0,
                        new_expense=0,
                        request_date=timezone.localtime(timezone.now()).date(),
                        channel=CovidRefinancingConst.CHANNELS.reactive,
                        comms_channel_1=CovidRefinancingConst.COMMS_CHANNELS.email,
                        comms_channel_2=CovidRefinancingConst.COMMS_CHANNELS.pn
                    )
                    loan_refinancing_request = LoanRefinancingRequest.objects. \
                        create(**loan_refinancing_request_dict)

            except (NotEligibleLoanStatus, RefinancingRequestOnGoingStatus, RefinancingAlreadyExist) as error:
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

                loan_ref_req_campaign = LoanRefinancingRequestCampaign.objects.create(
                    loan_refinancing_request=loan_refinancing_request,
                    account_id=refinancing_data['account_id'],
                    campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
                    expired_at=refinancing_data['expired_at'],
                    status=status,
                    extra_data=extra_data
                )

            try:
                if not errors.get('reason'):
                    # send email, pn
                    loan_refinancing_email = CovidLoanRefinancingEmail(loan_refinancing_request)
                    loan_refinancing_email.send_offer_refinancing_email()
                    errors['email_sent'] = True
                    loan_refinancing_pn = CovidLoanRefinancingPN(loan_refinancing_request)
                    loan_refinancing_pn.send_offer_refinancing_pn()
                    errors['notifications_sent'] = True
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


def validation_condition(account):
    # if account.ever_entered_B5:
    #     raise EverEnteredB5('Account detected ever entered B5')
    if not account.get_all_active_loan():
        raise NotEligibleLoanStatus('Invalid doesnt have active loan')
    exist_loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        account=account, status=CovidRefinancingConst.STATUSES.requested
    ).values('id').exists()
    if exist_loan_refinancing_request:
        raise RefinancingAlreadyExist('Already have loan refinancing with requested status')
    invalid_loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        account=account, status__in=CovidRefinancingConst.REACTIVE_OFFER_STATUS_SELECTED_OR_APPROVED
    ).values('id')
    if invalid_loan_refinancing_request:
        raise RefinancingRequestOnGoingStatus('Invalid loan refinancing request status')


def change_following_process_status_to_expired(account):
    LoanRefinancingRequest.objects.filter(
        account=account, status__in=list(CovidRefinancingConst.NEW_PROACTIVE_STATUSES.__dict__.values())
    ).update(
        expire_in_days=0,
        status=CovidRefinancingConst.STATUSES.expired,
        udate=timezone.localtime(timezone.now())
    )
    update_va_bni_transaction.delay(
        account.id,
        'account_payment.views.views_api_v2.UpdateCheckoutRequestStatus',
    )


class NotEligibleLoanStatus(Exception):
    pass


class RefinancingRequestOnGoingStatus(Exception):
    pass


class RefinancingAlreadyExist(Exception):
    pass


class EverEnteredB5(Exception):
    pass

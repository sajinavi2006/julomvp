from __future__ import division
from builtins import str
import logging
import sys
import csv
from django.utils import timezone, dateparse
from django.core.management.base import BaseCommand
from django.db import transaction

from juloserver.account.models import Account
from juloserver.account_payment.services.account_payment_related import (
    update_checkout_experience_status_to_cancel,
)
from juloserver.integapiv1.tasks import update_va_bni_transaction
from juloserver.loan_refinancing.models import (
    LoanRefinancingRequest,
    LoanRefinancingOffer,
    LoanRefinancingRequestCampaign,
    WaiverRequest,
)
from juloserver.loan_refinancing.constants import CovidRefinancingConst, Campaign
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.loan_refinancing.management.commands.collection_offer_R4_for_special_cohort_j1 import (
    generate_waiver_offer,
    validate_condition,
    vallidate_prerequisite_amount,
    NotEligibleLoanStatus,
    RefinancingRequestOnGoingStatus,
    ZeroPrerequisiteAmount,
    MaxCapRule,
    validate_expire_date,
    InvalidExpireDate,
    validate_lender,
    InvalidLender,
    validate_dpd,
    InvalidDpd,
)
from juloserver.minisquad.tasks2.notifications import (
    send_r4_promo_for_b5_lender_jtf,
    send_r4_promo_blast,
)
from juloserver.minisquad.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('-f', '--file', type=str, help='Define file name')
        parser.add_argument('-f', '--queue', type=str, help='Define queue')

    def handle(self, **options):
        path = options.get('file')
        queue = options.get('queue', 'retrofix_normal')

        is_lender_validation = False
        allowed_lender = []
        is_dpd_validation = False
        dpd_start = 0
        dpd_end = 0

        promo_blast_fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.WAIVER_R4_PROMO_BLAST, is_active=True
        ).last()
        if promo_blast_fs:
            parameters = promo_blast_fs.parameters
            campaign_name = parameters.get('campaign_name')
            validation_settings = parameters.get('validation_settings')
            if validation_settings:
                lender_validation_settings = validation_settings.get('lender')
                dpd_validation_settings = validation_settings.get('dpd')
                if lender_validation_settings:
                    is_lender_validation = lender_validation_settings.get(
                        'is_lender_validation', False
                    )
                    allowed_lender = lender_validation_settings.get('allowed_lender')
                if dpd_validation_settings:
                    is_dpd_validation = dpd_validation_settings.get('is_dpd_validation', False)
                    dpd_start = dpd_validation_settings.get('dpd_start')
                    dpd_end = dpd_validation_settings.get('dpd_end')

        with open(path, 'r') as csvfile:
            csv_rows = csv.DictReader(csvfile, delimiter=',')
            rows = [r for r in csv_rows]

        for refinancing_data in rows:
            errors = {'email_sent': False, 'notifications_sent': False, 'sms_sent': False}
            loan_refinancing_request = None
            waiver_request_id = None
            try:
                with transaction.atomic():
                    account = Account.objects.get(id=refinancing_data['account_id'])
                    expire_date = dateparse.parse_date(refinancing_data['expired_at'])
                    if not expire_date:
                        #   convert 10/31/2024 to 2024-31-10
                        date_list = refinancing_data['expired_at'].split('/')
                        m = date_list[0]
                        d = date_list[1]
                        y = date_list[2]
                        expire_date = dateparse.parse_date(f'{y}-{m}-{d}')
                    validate_expire_date(expire_date)
                    validate_condition(account)
                    if is_lender_validation:
                        validate_lender(refinancing_data['dab_lender'].split(', '), allowed_lender)
                    if is_dpd_validation:
                        validate_dpd(int(refinancing_data['dpd']), dpd_start, dpd_end)
                    # change the ongoing refinancing request of  Email Sent, Form Viewed,
                    # Offer Generated to Expired
                    LoanRefinancingRequest.objects.filter(
                        account=account, status__in=['Email Sent', 'Form Viewed', 'Offer Generated']
                    ).update(
                        expire_in_days=0,
                        status=CovidRefinancingConst.STATUSES.expired,
                        udate=timezone.localtime(timezone.now()),
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
                    expire_in_days = (
                        dateparse.parse_date(refinancing_data['expired_at'])
                        - timezone.localtime(timezone.now()).date()
                    ).days

                    waiver_request_id, waiver_offer_data = generate_waiver_offer(
                        account,
                        refinancing_data,
                        expire_in_days,
                        refinancing_data['expired_at'],
                        product_line_code=app.product_line_code,
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
                        prerequisite_amount=waiver_offer_data['prerequisite_amount'],
                        total_latefee_discount=waiver_offer_data['total_latefee_discount'],
                    )
                    loan_refinancing_request = LoanRefinancingRequest.objects.create(
                        **loan_refinancing_request_dict
                    )

                    # create loan refinance offer
                    LoanRefinancingOffer.objects.create(
                        loan_refinancing_request=loan_refinancing_request, **waiver_offer_data
                    )
                    update_va_bni_transaction.delay(
                        account.id,
                        'management.commands.collection_offer_R4_for_dpd_180',
                        waiver_offer_data['prerequisite_amount'],
                    )

            except (
                NotEligibleLoanStatus,
                RefinancingRequestOnGoingStatus,
                ZeroPrerequisiteAmount,
                MaxCapRule,
                InvalidExpireDate,
                InvalidLender,
                InvalidDpd,
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
                WaiverRequest.objects.filter(pk=waiver_request_id).update(
                    loan_refinancing_request=loan_refinancing_request
                )
                # create Historical of Special R4
                loan_ref_req_campaign = LoanRefinancingRequestCampaign.objects.create(
                    loan_refinancing_request=loan_refinancing_request,
                    account_id=refinancing_data['account_id'],
                    campaign_name=campaign_name,
                    expired_at=refinancing_data['expired_at'],
                    principal_waiver=refinancing_data['principal_waiver'],
                    interest_waiver=refinancing_data['interest_waiver'],
                    late_fee_waiver=refinancing_data['late_fee_waiver'],
                    offer=refinancing_data['offer'],
                    status=status,
                    extra_data=extra_data,
                )

            try:
                if not errors.get('reason'):

                    logger.info(
                        {
                            'action': 'email_promo_r4_b5',
                            'status': 'start send_r4_promo',
                        }
                    )

                    dpd = int(refinancing_data['dpd'])

                    if dpd >= 181:
                        send_r4_promo_blast.apply_async(
                            kwargs={
                                'loan_refinancing_request_id': loan_refinancing_request.id,
                                'dab_lender': refinancing_data.get('dab_lender'),
                                'dpd': refinancing_data.get('dpd'),
                            },
                            queue=queue,
                        )
                    elif (dpd < 180) and (dpd >= 91):
                        send_r4_promo_for_b5_lender_jtf.apply_async(
                            kwargs={
                                'loan_refinancing_request_id': 'loan_refinancing_request.id',
                                'api_key': promo_blast_fs.parameters.get('email_settings').get(
                                    'api_key'
                                )
                                if promo_blast_fs
                                else '',
                            },
                            queue=queue,
                        )

                    errors['email_sent'] = True
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Success created for account id {refinancing_data['account_id']}"
                        )
                    )
            except Exception as error:
                self.stdout.write(self.style.ERROR(str(error)))
                self.stdout.write(self.style.ERROR(str(error)))
                sentry_client = get_julo_sentry_client()
                sentry_client.captureException()
                errors['reason'] = str(error)
                loan_ref_req_campaign.update_safely(extra_data=errors)

from juloserver.account.models import Account
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.cohort_campaign_automation.models import (
    CollectionCohortCampaignAutomation,
    CollectionCohortCampaignEmailTemplate,
)
from typing import Any
from django.db import transaction
from juloserver.loan_refinancing.management.commands.collection_offer_R4_for_special_cohort_j1 import (  # noqa
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
    InstallmentOutOfRange,
)
from django.utils import timezone
from juloserver.account_payment.services.account_payment_related import (
    update_checkout_experience_status_to_cancel,
)
from juloserver.loan_refinancing.models import (
    LoanRefinancingRequest,
    LoanRefinancingOffer,
    LoanRefinancingRequestCampaign,
    WaiverRequest,
)
from juloserver.integapiv1.tasks import update_va_bni_transaction
from juloserver.julo.clients import get_julo_sentry_client
import csv
from juloserver.julo.models import FeatureSetting
from juloserver.minisquad.constants import FeatureNameConst


class DuplicatedException(Exception):
    pass


def check_duplicate_campaign_name(campaign_name: str) -> bool:
    return CollectionCohortCampaignAutomation.objects.filter(campaign_name=campaign_name).exists()


def validation_csv_file(csv_file):
    try:
        promo_blast_fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.WAIVER_R4_PROMO_BLAST, is_active=True
        ).last()
        csv_headers = []
        offer = 'R4'
        if promo_blast_fs:
            parameters = promo_blast_fs.parameters
            csv_headers = parameters.get('campaign_automation', {}).get('csv_headers')

        file = csv_file.decode('utf-8')
        rows = csv.DictReader(file.splitlines())
        try:
            for r in rows:
                offer = r['offer']
                break
        except Exception:
            pass
        headers = rows.fieldnames
        if csv_headers != headers:
            raise Exception('Header csv tidak sesuai')

    except Exception as e:
        return False, str(e), offer

    return True, '', offer


def process_cohort_campaign_automation(csv_datas: Any, campaign_rules: dict):
    from juloserver.cohort_campaign_automation.tasks import send_cohort_campaign_email

    is_lender_validation = campaign_rules.get('is_lender_validation')
    allowed_lender = campaign_rules.get('allowed_lender')
    is_dpd_validation = campaign_rules.get('is_dpd_validation')
    dpd_start = campaign_rules.get('dpd_start')
    dpd_end = campaign_rules.get('dpd_end')
    api_key = campaign_rules.get('api_key')
    queue = campaign_rules.get('queue')
    campaign_id = campaign_rules.get('campaign_id')

    cohort_campaign = CollectionCohortCampaignAutomation.objects.filter(pk=campaign_id).last()
    campaign_email = CollectionCohortCampaignEmailTemplate.objects.filter(
        campaign_automation=cohort_campaign
    ).last()
    email_execution_times = [campaign_email.email_blast_date]
    for email_blast_date in campaign_email.additional_email_blast_dates:
        email_execution_times.append(email_blast_date)
    for csv_data in csv_datas:
        errors = {'email_sent': False}
        loan_refinancing_request = None
        waiver_request_id = None
        try:
            with transaction.atomic():
                account = Account.objects.get(id=csv_data['account_id'])
                expire_date = cohort_campaign.end_date
                expire_date_str = expire_date.strftime('%Y-%m-%d')
                validate_expire_date(expire_date)
                validate_condition(account)
                if is_lender_validation:
                    validate_lender(csv_data['dab_lender'].split(', '), allowed_lender)
                if is_dpd_validation:
                    validate_dpd(int(csv_data['dpd']), dpd_start, dpd_end)
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
                new_affordability = float(1)

                expire_in_days = (expire_date - timezone.localtime(timezone.now()).date()).days

                waiver_request_id, waiver_offer_data = generate_waiver_offer(
                    account,
                    csv_data,
                    expire_in_days,
                    expire_date_str,
                    product_line_code=app.product_line_code,
                )
                # check the prerequisite amount
                vallidate_prerequisite_amount(waiver_offer_data['prerequisite_amount'])
                loan_refinancing_request_dict = dict(
                    account_id=csv_data['account_id'],
                    affordability_value=new_affordability,
                    product_type=csv_data["offer"],
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
                    'cohort_campaign_automation.services.process_cohort_campaign_automation',
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
            InstallmentOutOfRange,
        ) as error:
            errors['reason'] = str(error)
        except Exception as error:
            errors['reason'] = str(error)
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
                account_id=csv_data['account_id'],
                campaign_name=cohort_campaign.campaign_name,
                expired_at=expire_date,
                principal_waiver=csv_data['principal_waiver'],
                interest_waiver=csv_data['interest_waiver'],
                late_fee_waiver=csv_data['late_fee_waiver'],
                offer=csv_data['offer'],
                status=status,
                extra_data=extra_data,
            )

        try:
            if not errors.get('reason'):
                for email_execution_time in email_execution_times:
                    send_cohort_campaign_email.apply_async(
                        kwargs={
                            'loan_refinancing_request_id': loan_refinancing_request.id,
                            'cohort_campaign_email_id': campaign_email.id,
                            'api_key': api_key,
                        },
                        queue=queue,
                        eta=email_execution_time,
                    )
                errors['email_sent'] = True
        except Exception as error:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            errors['reason'] = str(error)
            loan_ref_req_campaign.update_safely(extra_data=errors)

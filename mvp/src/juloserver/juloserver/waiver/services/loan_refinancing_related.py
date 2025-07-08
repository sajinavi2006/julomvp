from datetime import timedelta, datetime
from django.utils import timezone

from juloserver.payback.constants import WaiverConst
from juloserver.payback.models import WaiverTemp
from juloserver.loan_refinancing.models import (
    LoanRefinancingRequest,
    LoanRefinancingOffer,
)
from juloserver.loan_refinancing.tasks import (
    send_email_refinancing_offer_selected,
    send_sms_covid_refinancing_offer_selected,
    send_pn_covid_refinancing_offer_selected,
)
from juloserver.loan_refinancing.services.comms_channels import (
    send_loan_refinancing_request_approved_notification,
    send_loan_refinancing_request_activated_notification,
)
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.account.services.account_related import process_change_account_status
from juloserver.account.constants import AccountConstant


def loan_refinancing_request_update_for_j1_waiver(account_payment):
    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        account=account_payment.account,
        status=CovidRefinancingConst.STATUSES.offer_selected
    ).last()

    if loan_refinancing_request:
        loan_refinancing_offer = LoanRefinancingOffer.objects.filter(
            loan_refinancing_request=loan_refinancing_request,
            product_type__in=CovidRefinancingConst.waiver_products(),
            is_accepted=True,
            is_latest=True
        ).last()
        if loan_refinancing_offer:
            waiver_temp = WaiverTemp.objects.filter(
                account=account_payment.account,
                status=WaiverConst.ACTIVE_STATUS
            ).last()

            if waiver_temp:
                update_offer = False
                pass_latefee = int(waiver_temp.late_fee_waiver_amt) > 0
                pass_interest = int(waiver_temp.interest_waiver_amt) > 0
                pass_principal = int(waiver_temp.principal_waiver_amt) > 0

                if pass_latefee and pass_interest and pass_principal and \
                        loan_refinancing_request.product_type == CovidRefinancingConst.PRODUCTS.r4:
                    send_email_refinancing_offer_selected.delay(loan_refinancing_request.id)
                    send_pn_covid_refinancing_offer_selected.delay(loan_refinancing_request.id)
                    send_sms = True
                    comms_list = loan_refinancing_request.comms_channel_list()
                    if loan_refinancing_request.channel == CovidRefinancingConst.CHANNELS.reactive \
                            and CovidRefinancingConst.COMMS_CHANNELS.sms not in comms_list:
                        send_sms = False

                    if send_sms:
                        send_sms_covid_refinancing_offer_selected.delay(loan_refinancing_request.id)

                    update_offer = True

                elif pass_latefee and \
                        loan_refinancing_request.product_type == CovidRefinancingConst.PRODUCTS.r5:
                    loan_refinancing_request.update_safely(
                        status=CovidRefinancingConst.STATUSES.approved)
                    send_loan_refinancing_request_approved_notification(loan_refinancing_request)
                    update_offer = True

                elif pass_latefee and pass_interest and \
                        loan_refinancing_request.product_type == CovidRefinancingConst.PRODUCTS.r6:
                    loan_refinancing_request.update_safely(
                        status=CovidRefinancingConst.STATUSES.approved)
                    send_loan_refinancing_request_approved_notification(loan_refinancing_request)
                    update_offer = True

                if update_offer:
                    loan_refinancing_offer.update_safely(
                        total_latefee_discount=int(waiver_temp.late_fee_waiver_amt),
                        total_interest_discount=int(waiver_temp.interest_waiver_amt),
                        total_principal_discount=int(waiver_temp.principal_waiver_amt),
                        prerequisite_amount=int(waiver_temp.need_to_pay)
                    )
                    loan_refinancing_request.update_safely(
                        total_latefee_discount=int(waiver_temp.late_fee_waiver_amt),
                        prerequisite_amount=int(waiver_temp.need_to_pay)
                    )


def get_j1_loan_refinancing_request(account, is_reactive=False):
    statuses = [CovidRefinancingConst.STATUSES.approved]
    if is_reactive:
        statuses.push(CovidRefinancingConst.STATUSES.offer_selected)
    return LoanRefinancingRequest.objects.filter(account=account).filter(status__in=statuses).last()


def check_eligibility_of_j1_loan_refinancing(loan_refinancing_request, paid_date, paid_amount=0):
    if loan_refinancing_request.status == CovidRefinancingConst.STATUSES.expired:
        return False

    date_ref = loan_refinancing_request.form_submitted_ts or \
        loan_refinancing_request.request_date or loan_refinancing_request.cdate
    if type(date_ref) == datetime:
        date_ref = timezone.localtime(date_ref).date()

    loan_refinancing_offer = loan_refinancing_request.loanrefinancingoffer_set.filter(
        is_accepted=True).last()
    if loan_refinancing_offer and loan_refinancing_offer.offer_accepted_ts:
        date_ref = timezone.localtime(loan_refinancing_offer.offer_accepted_ts).date()

    first_payment_due_date = date_ref + timedelta(days=loan_refinancing_request.expire_in_days)

    if paid_date > first_payment_due_date:
        loan_refinancing_request.update_safely(status=CovidRefinancingConst.STATUSES.expired)
        return False

    if paid_amount < loan_refinancing_request.prerequisite_amount:
        return False

    return True


def activate_j1_loan_refinancing_waiver(account, paid_date, paid_amount):
    loan_refinancing_request = get_j1_loan_refinancing_request(account)
    if loan_refinancing_request and check_eligibility_of_j1_loan_refinancing(
            loan_refinancing_request, paid_date.date(), paid_amount):
        loan_refinancing_request.change_status(CovidRefinancingConst.STATUSES.activated)
        loan_refinancing_request.offer_activated_ts = timezone.localtime(timezone.now())
        loan_refinancing_request.save()
        loan_refinancing_request.refresh_from_db()
        send_loan_refinancing_request_activated_notification(loan_refinancing_request)
        if loan_refinancing_request.product_type != CovidRefinancingConst.PRODUCTS.r4:
            return
        process_change_account_status(
            account, AccountConstant.STATUS_CODE.suspended, "R4 cool off period")

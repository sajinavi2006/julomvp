from ..constants import CovidRefinancingConst
from ..tasks import (send_email_covid_refinancing_approved,
                     send_sms_covid_refinancing_approved,
                     send_pn_covid_refinancing_approved,
                     send_email_covid_refinancing_activated,
                     send_sms_covid_refinancing_activated,
                     send_pn_covid_refinancing_activated,
                     send_email_covid_refinancing_reminder_to_pay_minus_1,
                     send_email_covid_refinancing_reminder_to_pay_minus_2,
                     send_sms_covid_refinancing_reminder_to_pay_minus_1,
                     send_sms_covid_refinancing_reminder_to_pay_minus_2,
                     send_pn_covid_refinancing_reminder_to_pay_minus_1,
                     send_pn_covid_refinancing_reminder_to_pay_minus_2,
                     send_email_covid_refinancing_reminder,
                     send_email_refinancing_offer_selected_minus_1,
                     send_email_refinancing_offer_selected_minus_2,
                     send_pn_covid_refinancing_reminder_offer_selected_2,
                     send_pn_covid_refinancing_reminder_offer_selected_1,
                     send_sms_covid_refinancing_reminder_offer_selected_2,
                     send_sms_covid_refinancing_reminder_offer_selected_1,
                     send_robocall_refinancing_reminder_minus_3,
                     send_proactive_email_reminder,
                     send_proactive_pn_reminder,
                     send_proactive_robocall_reminder,
                     send_proactive_sms_reminder,
                     send_email_covid_refinancing_opt,
                     send_email_multiple_payment_ptp,
                     send_email_multiple_payment_expiry,
                     send_email_multiple_payment_minus_expiry,
                     send_email_requested_status_campaign_reminder_to_pay_minus_2,
                     send_email_requested_status_campaign_reminder_to_pay_minus_1,
                     send_pn_requested_status_campaign_reminder_to_pay_minus_2,
                     send_pn_requested_status_campaign_reminder_to_pay_minus_1,
                     send_email_sos_refinancing_activated,
                     )
from django.utils import timezone

from ...julo.constants import AddressPostalCodeConst
from ...julo.models import Payment, Loan, Application


def send_loan_refinancing_request_multiple_payment_expiry_minus_notification(loan_refinancing_req):
    if loan_refinancing_req.is_multiple_ptp_payment:
        send_email_multiple_payment_minus_expiry.delay(loan_refinancing_req.id)


def send_loan_refinancing_request_multiple_payment_expiry_notification(loan_refinancing_req):
    if loan_refinancing_req.is_multiple_ptp_payment:
        send_email_multiple_payment_expiry.delay(loan_refinancing_req.id)


def send_loan_refinancing_request_approved_notification(loan_refinancing_req):
    if loan_refinancing_req.is_multiple_ptp_payment:
        send_email_multiple_payment_ptp.delay(loan_refinancing_req.id)
        return

    communication_list = loan_refinancing_req.comms_channel_list()
    if loan_refinancing_req.channel == CovidRefinancingConst.CHANNELS.reactive:
        if CovidRefinancingConst.COMMS_CHANNELS.email in communication_list:
            send_email_covid_refinancing_approved.delay(loan_refinancing_req.id)
        if CovidRefinancingConst.COMMS_CHANNELS.sms in communication_list:
            send_sms_covid_refinancing_approved.delay(loan_refinancing_req.id)
        if CovidRefinancingConst.COMMS_CHANNELS.pn in communication_list:
            send_pn_covid_refinancing_approved.delay(loan_refinancing_req.id)
    else:
        send_email_covid_refinancing_approved.delay(loan_refinancing_req.id)
        send_sms_covid_refinancing_approved.delay(loan_refinancing_req.id)
        send_pn_covid_refinancing_approved.delay(loan_refinancing_req.id)


def send_loan_refinancing_request_activated_notification(loan_refinancing_req):
    communication_list = loan_refinancing_req.comms_channel_list()
    if loan_refinancing_req.channel == CovidRefinancingConst.CHANNELS.reactive:
        if CovidRefinancingConst.COMMS_CHANNELS.email in communication_list:
            send_email_covid_refinancing_activated.apply_async((loan_refinancing_req.id,), countdown=120)
        if CovidRefinancingConst.COMMS_CHANNELS.pn in communication_list:
            send_pn_covid_refinancing_activated.apply_async((loan_refinancing_req.id,), countdown=120)
    else:
        send_email_covid_refinancing_activated.apply_async((loan_refinancing_req.id,), countdown=120)
        send_pn_covid_refinancing_activated.apply_async((loan_refinancing_req.id,), countdown=120)


def send_sos_refinancing_request_activated_notification(loan_refinancing_req):
    communication_list = loan_refinancing_req.comms_channel_list()
    if loan_refinancing_req.channel == CovidRefinancingConst.CHANNELS.reactive:
        if CovidRefinancingConst.COMMS_CHANNELS.email in communication_list:
            send_email_sos_refinancing_activated.delay(loan_refinancing_req.id)


def send_loan_refinancing_request_reminder_minus_2(loan_refinancing_req):
    if loan_refinancing_req.is_multiple_ptp_payment:
        return

    if CovidRefinancingConst.COMMS_CHANNELS.email in loan_refinancing_req.comms_channel_list():
        send_email_covid_refinancing_reminder_to_pay_minus_2.delay(loan_refinancing_req.id)
    if CovidRefinancingConst.COMMS_CHANNELS.sms in loan_refinancing_req.comms_channel_list():
        send_sms_covid_refinancing_reminder_to_pay_minus_2.apply_async((loan_refinancing_req.id,),
                                                                       countdown=7200)
    if CovidRefinancingConst.COMMS_CHANNELS.pn in loan_refinancing_req.comms_channel_list():
        send_pn_covid_refinancing_reminder_to_pay_minus_2.apply_async((loan_refinancing_req.id,),
                                                                      countdown=3600)


def send_loan_refinancing_request_reminder_minus_1(loan_refinancing_req):
    if loan_refinancing_req.is_multiple_ptp_payment:
        return

    if CovidRefinancingConst.COMMS_CHANNELS.email in loan_refinancing_req.comms_channel_list():
        send_email_covid_refinancing_reminder_to_pay_minus_1.delay(loan_refinancing_req.id)
    if CovidRefinancingConst.COMMS_CHANNELS.sms in loan_refinancing_req.comms_channel_list():
        send_sms_covid_refinancing_reminder_to_pay_minus_1.apply_async((loan_refinancing_req.id,),
                                                                       countdown=7200)
    if CovidRefinancingConst.COMMS_CHANNELS.pn in loan_refinancing_req.comms_channel_list():
        send_pn_covid_refinancing_reminder_to_pay_minus_1.apply_async((loan_refinancing_req.id,),
                                                                      countdown=3600)


def send_loan_refinancing_request_reminder_offer_selected_2(loan_refinancing_req):
    if CovidRefinancingConst.COMMS_CHANNELS.email in loan_refinancing_req.comms_channel_list():
        send_email_refinancing_offer_selected_minus_2.delay(loan_refinancing_req.id)
    if CovidRefinancingConst.COMMS_CHANNELS.sms in loan_refinancing_req.comms_channel_list():
        send_sms_covid_refinancing_reminder_offer_selected_2.apply_async((loan_refinancing_req.id,),
                                                                         countdown=7200)
    if CovidRefinancingConst.COMMS_CHANNELS.pn in loan_refinancing_req.comms_channel_list():
        send_pn_covid_refinancing_reminder_offer_selected_2.apply_async((loan_refinancing_req.id,),
                                                                        countdown=3600)


def send_loan_refinancing_request_reminder_offer_selected_1(loan_refinancing_req):
    if CovidRefinancingConst.COMMS_CHANNELS.email in loan_refinancing_req.comms_channel_list():
        send_email_refinancing_offer_selected_minus_1.delay(loan_refinancing_req.id)
    if CovidRefinancingConst.COMMS_CHANNELS.sms in loan_refinancing_req.comms_channel_list():
        send_sms_covid_refinancing_reminder_offer_selected_1.apply_async((loan_refinancing_req.id,),
                                                                         countdown=7200)
    if CovidRefinancingConst.COMMS_CHANNELS.pn in loan_refinancing_req.comms_channel_list():
        send_pn_covid_refinancing_reminder_offer_selected_1.apply_async((loan_refinancing_req.id,),
                                                                        countdown=3600)


def send_loan_refinancing_robocall_reminder_minus_3(loan_refinancing_req):
    params = dict(loan_refinancing_request_id=loan_refinancing_req.id)
    today = timezone.localtime(timezone.now())
    params["filter_data"] = None
    params["limit"] = 0
    if today.hour == 10:
        params["filter_data"] = dict(cdate__hour=8)
        params["limit"] = 1
    elif today.hour == 12:
        params["filter_data"] = dict(cdate__hour__in=[8, 10])
        params["limit"] = 2

    send_robocall_refinancing_reminder_minus_3.delay(**params)


def send_proactive_refinancing_reminder(loan_refinancing_req, reminder_type, day, new_status=None):
    reminder_task_dict = {
        "email": send_proactive_email_reminder,
        "pn": send_proactive_pn_reminder,
        "robocall": send_proactive_robocall_reminder,
        "sms": send_proactive_sms_reminder,
    }
    params = dict(loan_refinancing_req_id=loan_refinancing_req.id)
    if reminder_type == "robocall":
        today = timezone.localtime(timezone.now())
        params["filter_data"] = None
        params["limit"] = 0
        if today.hour == 10:
            params["filter_data"] = dict(cdate__hour=8)
            params["limit"] = 1
        elif today.hour == 12:
            params["filter_data"] = dict(cdate__hour__in=[8, 10])
            params["limit"] = 2
    else:
        params["new_status"] = new_status
        if reminder_type != "sms":
            params["day"] = day

    reminder_task_dict[reminder_type].delay(**params)


def send_loan_refinancing_request_offer_selected_notification(loan_refinancing_req):
    if CovidRefinancingConst.COMMS_CHANNELS.email in loan_refinancing_req.comms_channel_list():
        send_email_covid_refinancing_opt.delay(loan_refinancing_req.id)


def get_account_ids_for_specific_indonesia_timezone(timezone_part):
    address_kode_pos = AddressPostalCodeConst.WIB_POSTALCODE
    if timezone_part == 'WIT':
        address_kode_pos = AddressPostalCodeConst.WIT_POSTALCODE
    elif timezone_part == 'WITA':
        address_kode_pos = AddressPostalCodeConst.WITA_POSTALCODE

    account_ids = Application.objects.filter(
        account__isnull=False,
        address_kodepos__in=address_kode_pos
    ).distinct('account').values_list('account_id', flat=True)
    return account_ids


def get_loan_ids_for_specific_indonesia_timezone(timezone_part):
    address_kode_pos = AddressPostalCodeConst.WIB_POSTALCODE
    if timezone_part == 'WIT':
        address_kode_pos = AddressPostalCodeConst.WIT_POSTALCODE
    elif timezone_part == 'WITA':
        address_kode_pos = AddressPostalCodeConst.WITA_POSTALCODE

    loan_ids = Payment.objects.not_paid_active().filter(
        account_payment__isnull=True,
        loan__application__address_kodepos__in=address_kode_pos
    ).distinct('loan').values_list('loan_id', flat=True)
    return loan_ids


def send_loan_refinancing_requested_status_campaign_reminder_minus_2(loan_refinancing_req):
    send_email_requested_status_campaign_reminder_to_pay_minus_2.delay(loan_refinancing_req.id)
    send_pn_requested_status_campaign_reminder_to_pay_minus_2.apply_async((loan_refinancing_req.id,), countdown=3600)


def send_loan_refinancing_requested_status_campaign_reminder_minus_1(loan_refinancing_req):
    send_email_requested_status_campaign_reminder_to_pay_minus_1.delay(loan_refinancing_req.id)
    send_pn_requested_status_campaign_reminder_to_pay_minus_1.apply_async((loan_refinancing_req.id,), countdown=3600)

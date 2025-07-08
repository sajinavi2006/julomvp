
from datetime import (
    datetime,
    timedelta,
    date)
from django.utils import timezone

from .services.payment_related import (
    get_customer_data_from_dpd,
    get_gcm_ids_from_dpd)
from .interface import *
from .constants import RamadanCampaign
from juloserver.promo.models import PromoHistory


class RamadanEmailStrategy(EmailInterface):
    def get_customer_data(self, dpd=None, excluded_payment_ids=[]):
        return get_customer_data_from_dpd(dpd, excluded_payment_ids)

    def get_reminder_type(self, day):
        reminder_dict = {
            11: RamadanCampaign.INITIATIVE3_REMINDER_1,
            24: RamadanCampaign.INITIATIVE3_REMINDER_2,
            7: RamadanCampaign.INITIATIVE3_REMINDER_3
        }

        return reminder_dict[day]

    def send(self):
        from .tasks import send_ramadan_email

        today = timezone.localtime(timezone.now()).date()
        email1_start_date = (datetime.strptime(
            RamadanCampaign.EMAIL1_START_DATE, '%Y-%m-%d')).date()
        email1_end_date = (datetime.strptime(
            RamadanCampaign.EMAIL1_END_DATE, '%Y-%m-%d')).date()
        email2_start_date = (datetime.strptime(
            RamadanCampaign.EMAIL2_START_DATE, '%Y-%m-%d')).date()
        email2_end_date = (datetime.strptime(
            RamadanCampaign.EMAIL2_END_DATE, '%Y-%m-%d')).date()
        email1_initiative3_date = (datetime.strptime(
            RamadanCampaign.EMAIL1_INITIATIVE3_DATE, '%Y-%m-%d')).date()
        email2_initiative3_date = (datetime.strptime(
            RamadanCampaign.EMAIL2_INITIATIVE3_DATE, '%Y-%m-%d')).date()
        email3_initiative3_date = (datetime.strptime(
            RamadanCampaign.EMAIL3_INITIATIVE3_DATE, '%Y-%m-%d')).date()
        email_initiative3_date_list = (
            email1_initiative3_date,
            email2_initiative3_date,
            email3_initiative3_date
        )
        t_minus_7_payment_ids = []
        t_minus_3_payment_ids = []
        initiative3_payment_ids = []
        initiative3_reminder_type = ''
        excluded_payment_ids = PromoHistory.objects.filter(
            promo_type=RamadanCampaign.PROMO_INITIATIVE2_TYPE
        ).values_list('payment', flat=True)

        if email1_start_date <= today <= email1_end_date:
            t_minus_7_payment_ids = self.get_customer_data(RamadanCampaign.T_MINUS_7)

        if email2_start_date <= today <= email2_end_date:
            t_minus_3_payment_ids = self.get_customer_data(RamadanCampaign.T_MINUS_3)

        if today in email_initiative3_date_list:
            initiative3_payment_ids = self.get_customer_data(
                excluded_payment_ids=excluded_payment_ids
            )
            initiative3_reminder_type = self.get_reminder_type(today.day)

        for payment_id in initiative3_payment_ids:
            send_ramadan_email.delay(payment_id,
                                     RamadanCampaign.INITIATIVE3,
                                     initiative3_reminder_type)

        for payment_id in t_minus_7_payment_ids:
            send_ramadan_email.delay(payment_id,
                                     RamadanCampaign.INITIATIVE2,
                                     RamadanCampaign.T_MINUS_7)

        for payment_id in t_minus_3_payment_ids:
            send_ramadan_email.delay(payment_id,
                                     RamadanCampaign.INITIATIVE2,
                                     RamadanCampaign.T_MINUS_3)


class RamadanPnStrategy(PnInterface):
    def get_customer_data(self, dpd=None, excluded_payment_ids=[]):
        return get_gcm_ids_from_dpd(dpd, excluded_payment_ids)

    def get_reminder_type(self, day):
        reminder_dict = {
            14: RamadanCampaign.INITIATIVE3_REMINDER_1,
            18: RamadanCampaign.INITIATIVE3_REMINDER_2,
            22: RamadanCampaign.INITIATIVE3_REMINDER_3,
            29: RamadanCampaign.INITIATIVE3_REMINDER_4,
            3: RamadanCampaign.INITIATIVE3_REMINDER_5
        }

        return reminder_dict[day]

    def send(self):
        from .tasks import send_ramadan_pn

        today = timezone.localtime(timezone.now()).date()
        pn1_start_date = (datetime.strptime(
            RamadanCampaign.PN1_START_DATE, '%Y-%m-%d')).date()
        pn1_end_date = (datetime.strptime(
            RamadanCampaign.PN1_END_DATE, '%Y-%m-%d')).date()
        pn2_start_date = (datetime.strptime(
            RamadanCampaign.PN2_START_DATE, '%Y-%m-%d')).date()
        pn2_end_date = (datetime.strptime(
            RamadanCampaign.PN2_END_DATE, '%Y-%m-%d')).date()
        pn3_start_date = (datetime.strptime(
            RamadanCampaign.PN3_START_DATE, '%Y-%m-%d')).date()
        pn3_end_date = (datetime.strptime(
            RamadanCampaign.PN3_END_DATE, '%Y-%m-%d')).date()
        initiative3_pn1_date = (datetime.strptime(
            RamadanCampaign.PN1_INITIATIVE3_DATE, '%Y-%m-%d')).date()
        initiative3_pn2_date = (datetime.strptime(
            RamadanCampaign.PN2_INITIATIVE3_DATE, '%Y-%m-%d')).date()
        initiative3_pn3_date = (datetime.strptime(
            RamadanCampaign.PN3_INITIATIVE3_DATE, '%Y-%m-%d')).date()
        initiative3_pn4_date = (datetime.strptime(
            RamadanCampaign.PN4_INITIATIVE3_DATE, '%Y-%m-%d')).date()
        initiative3_pn5_date = (datetime.strptime(
            RamadanCampaign.PN5_INITIATIVE3_DATE, '%Y-%m-%d')).date()
        pn_initiative3_date_list = (
            initiative3_pn1_date,
            initiative3_pn2_date,
            initiative3_pn3_date,
            initiative3_pn4_date,
            initiative3_pn5_date
        )

        t_minus_7_gcm_ids = []
        t_minus_5_gcm_ids = []
        t_minus_3_gcm_ids = []
        initiative3_gcm_ids = []
        reminder_type = ''
        excluded_payment_ids = PromoHistory.objects.filter(
            promo_type=RamadanCampaign.PROMO_INITIATIVE2_TYPE
        ).values_list('payment', flat=True)

        if pn1_start_date <= today <= pn1_end_date:
            t_minus_7_gcm_ids = self.get_customer_data(RamadanCampaign.T_MINUS_7)

        if pn2_start_date <= today <= pn2_end_date:
            t_minus_5_gcm_ids = self.get_customer_data(RamadanCampaign.T_MINUS_5)

        if pn3_start_date <= today <= pn3_end_date:
            t_minus_3_gcm_ids = self.get_customer_data(RamadanCampaign.T_MINUS_3)

        if today in pn_initiative3_date_list:
            initiative3_gcm_ids = self.get_customer_data(
                excluded_payment_ids=excluded_payment_ids
            )
            reminder_type = self.get_reminder_type(today.day)

        for gcm_id in initiative3_gcm_ids:
            send_ramadan_pn.delay(
                gcm_id, RamadanCampaign.INITIATIVE3, reminder_type,
                RamadanCampaign.INITIATIVE3_PN_REMINDER_IMAGE)

        for gcm_id in t_minus_7_gcm_ids:
            send_ramadan_pn.delay(
                gcm_id, RamadanCampaign.INITIATIVE2, RamadanCampaign.T_MINUS_7,
                RamadanCampaign.INITIATIVE2_PN_REMINDER_1_IMAGE)

        for gcm_id in t_minus_5_gcm_ids:
            send_ramadan_pn.delay(
                gcm_id, RamadanCampaign.INITIATIVE2, RamadanCampaign.T_MINUS_5,
                RamadanCampaign.INITIATIVE2_PN_REMINDER_1_IMAGE)

        for gcm_id in t_minus_3_gcm_ids:
            send_ramadan_pn.delay(
                gcm_id, RamadanCampaign.INITIATIVE2, RamadanCampaign.T_MINUS_3,
                RamadanCampaign.INITIATIVE2_PN_REMINDER_2_IMAGE)


class RamadanSmsStrategy(SmsInterface):
    def get_customer_data(self, dpd=None, excluded_payment_ids=[]):
        return get_customer_data_from_dpd(dpd, excluded_payment_ids)

    def get_reminder_type(self, day):
        reminder_dict = {
            12: RamadanCampaign.INITIATIVE3_REMINDER_1,
            25: RamadanCampaign.INITIATIVE3_REMINDER_2,
            6: RamadanCampaign.INITIATIVE3_REMINDER_3,
        }

        return reminder_dict[day]

    def send(self):
        from .tasks import send_ramadan_sms

        today = timezone.localtime(timezone.now()).date()
        sms1_start_date = (datetime.strptime(
            RamadanCampaign.SMS1_START_DATE, '%Y-%m-%d')).date()
        sms1_end_date = (datetime.strptime(
            RamadanCampaign.SMS1_END_DATE, '%Y-%m-%d')).date()
        sms2_start_date = (datetime.strptime(
            RamadanCampaign.SMS2_START_DATE, '%Y-%m-%d')).date()
        sms2_end_date = (datetime.strptime(
            RamadanCampaign.SMS2_END_DATE, '%Y-%m-%d')).date()
        initiative3_sms1_date = (datetime.strptime(
            RamadanCampaign.SMS1_INITIATIVE3_DATE, '%Y-%m-%d')).date()
        initiative3_sms2_date = (datetime.strptime(
            RamadanCampaign.SMS2_INITIATIVE3_DATE, '%Y-%m-%d')).date()
        initiative3_sms3_date = (datetime.strptime(
            RamadanCampaign.SMS3_INITIATIVE3_DATE, '%Y-%m-%d')).date()
        sms_initiative3_date_list = (
            initiative3_sms1_date,
            initiative3_sms2_date,
            initiative3_sms3_date
        )

        t_minus_6_payment_ids = []
        t_minus_4_payment_ids = []
        initiative3_payment_ids = []
        reminder_type = ''
        excluded_payment_ids = PromoHistory.objects.filter(
            promo_type=RamadanCampaign.PROMO_INITIATIVE2_TYPE
        ).values_list('payment', flat=True)

        if sms1_start_date <= today <= sms1_end_date:
            t_minus_6_payment_ids = self.get_customer_data(RamadanCampaign.T_MINUS_6)

        if sms2_start_date <= today <= sms2_end_date:
            t_minus_4_payment_ids = self.get_customer_data(RamadanCampaign.T_MINUS_4)

        if today in sms_initiative3_date_list:
            initiative3_payment_ids = self.get_customer_data(
                excluded_payment_ids=excluded_payment_ids
            )
            reminder_type = self.get_reminder_type(today.day)

        for payment_id in initiative3_payment_ids:
            send_ramadan_sms.delay(payment_id, RamadanCampaign.INITIATIVE3, reminder_type)

        for payment_id in t_minus_6_payment_ids:
            send_ramadan_sms.delay(payment_id, RamadanCampaign.INITIATIVE2,
                                   RamadanCampaign.T_MINUS_6)

        for payment_id in t_minus_4_payment_ids:
            send_ramadan_sms.delay(payment_id, RamadanCampaign.INITIATIVE2,
                                   RamadanCampaign.T_MINUS_4)

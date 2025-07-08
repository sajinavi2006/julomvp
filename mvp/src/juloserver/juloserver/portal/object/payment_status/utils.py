#!/usr/bin/python
from juloserver.julo.constants import BucketConst
import os
import shutil
import logging
import re

from itertools import chain
from operator import attrgetter
from dateutil.relativedelta import relativedelta
from datetime import date

from juloserver.julo.models import Application, ApplicationNote, ProductLine
from django.db.models import Value, CharField
from django.utils import timezone
from juloserver.account_payment.models import AccountPaymentNote, AccountPayment

logger = logging.getLogger(__name__)


def get_app_list_history(app_object):
    app_notes = (
        ApplicationNote.objects.filter(application_id=app_object.id)
        .order_by('-cdate')
        .annotate(type_data=Value('Notes', output_field=CharField()))
    )

    return app_notes


def get_wallet_list_note(customer):
    wallet_notes = customer.customerwalletnote_set.all().order_by('-cdate').annotate(
        type_data=Value('Notes', output_field=CharField()))

    return wallet_notes


def get_list_history(payment_object, collection_assignment_movement_history=None):
    pmt_histories = payment_object.paymentstatuschange_set.all().annotate(
        type_data=Value('Status Change', output_field=CharField()))
    pmt_notes = payment_object.paymentnote_set.all().annotate(
        type_data=Value('Notes', output_field=CharField()))
    if collection_assignment_movement_history:
        return sorted(
            chain(pmt_histories, pmt_notes, collection_assignment_movement_history),
            key=lambda instance: instance.cdate, reverse=True)

    return sorted(
        chain(pmt_histories, pmt_notes),
        key=lambda instance: instance.cdate, reverse=True)


def get_acc_pmt_list_history(payment_object, collection_assignment_movement_history=None):
    act_pmt_histories = payment_object.accountpaymentstatushistory_set.all().annotate(
        type_data=Value('Status Change', output_field=CharField()))
    act_pmt_notes = payment_object.accountpaymentnote_set.filter(
        account_payment=payment_object).annotate(type_data=Value('Notes', output_field=CharField()))
    if collection_assignment_movement_history:
        return sorted(
            chain(act_pmt_histories, act_pmt_notes, collection_assignment_movement_history),
            key=lambda instance: instance.cdate, reverse=True)

    return sorted(
        chain(act_pmt_histories, act_pmt_notes),
        key=lambda instance: instance.cdate, reverse=True)


def get_list_email_sms(payment_object):
    email_histories = payment_object.emailhistory_set.all().annotate(
        type_data=Value('Email', output_field=CharField()))
    sms_histories = payment_object.smshistory_set.all().annotate(
        type_data=Value('Sms', output_field=CharField()))

    return sorted(
        chain(email_histories, sms_histories),
        key=lambda instance: instance.cdate, reverse=True)


def payment_parse_pass_due(str_pass_due):
    if str_pass_due == "ptp":
        return ['PTP', 'PTP']
    elif 'Robo' in str_pass_due:
        return [str_pass_due, str_pass_due]
    elif 'whatsapp_blasted' in str_pass_due:
        return [str_pass_due, str_pass_due]
    else:
        if (str_pass_due == "minusone"):
            str_pass_due = -1
        elif (str_pass_due == "notcalled"):
            str_pass_due = 1000
        elif (str_pass_due == "duetoday"):
            str_pass_due = 1001
        elif (str_pass_due == "grab"):
            str_pass_due = 1002
        elif (str_pass_due == "whatsapp"):
            str_pass_due = 1003
        elif str_pass_due == "collection_agent_1to4":
            str_pass_due = 10014
        elif str_pass_due == "collection_agent_5to15":
            str_pass_due = 100515
        elif str_pass_due == "collection_agent_16to29":
            str_pass_due = 1001629
        elif str_pass_due == "collection_agent_30to44":
            str_pass_due = 1003044
        elif str_pass_due == "collection_agent_45to59":
            str_pass_due = 1004559
        elif str_pass_due == "collection_agent_60to74":
            str_pass_due = 1006074
        elif str_pass_due == "collection_agent_75to89":
            str_pass_due = 1007589
        elif str_pass_due == "collection_agent_90to119":
            str_pass_due = 10090119
        elif str_pass_due == "collection_agent_120to179":
            str_pass_due = 100120179
        elif str_pass_due == "collection_agent_plus180":
            str_pass_due = 111180
        elif str_pass_due == "collection_agent_2_ptp":
            str_pass_due = 1000001
        elif str_pass_due == "collection_agent_3_ptp":
            str_pass_due = 1000002
        elif str_pass_due == "collection_agent_3_ignore_called":
            str_pass_due = 1000003
        elif str_pass_due == "collection_agent_2_whatsapp":
            str_pass_due = 1000004
        elif str_pass_due == "collection_agent_3_whatsapp":
            str_pass_due = 1000005
        elif str_pass_due == "collection_agent_4_ptp":
            str_pass_due = 1000006
        elif str_pass_due == "collection_agent_5_ptp":
            str_pass_due = 1000007
        elif str_pass_due == "collection_agent_4_whatsapp":
            str_pass_due = 1000008
        elif str_pass_due == "collection_agent_5_whatsapp":
            str_pass_due = 1000009
        elif str_pass_due == "collection_agent_4_ignore_called":
            str_pass_due = 1000010
        elif str_pass_due == "collection_agent_5_ignore_called":
            str_pass_due = 1000011
        elif str_pass_due == "collection_supervisor_1to4":
            str_pass_due = 10214
        elif str_pass_due == "collection_supervisor_5to15":
            str_pass_due = 102515
        elif str_pass_due == "collection_supervisor_16to29":
            str_pass_due = 1021629
        elif str_pass_due == "collection_supervisor_30to44":
            str_pass_due = 1023044
        elif str_pass_due == "collection_supervisor_45to59":
            str_pass_due = 1024559
        elif str_pass_due == "collection_supervisor_60to74":
            str_pass_due = 1026074
        elif str_pass_due == "collection_supervisor_75to89":
            str_pass_due = 1027589
        elif str_pass_due == "collection_supervisor_90to119":
            str_pass_due = 10290119
        elif str_pass_due == "collection_supervisor_120to179":
            str_pass_due = 102120179
        elif str_pass_due == "collection_supervisor_plus180":
            str_pass_due = 112180
        elif str_pass_due == "collection_supervisor_plus101":
            str_pass_due = 112101
        elif str_pass_due == "collection_supervisor_ptp":
            str_pass_due = 1020001
        elif str_pass_due == "collection_supervisor_ignore_called":
            str_pass_due = 1020002
        elif str_pass_due == "collection_supervisor_whatsapp":
            str_pass_due = 1020003
        elif str_pass_due == 'collection_bucket_1_to4':
            str_pass_due = 1030014
        elif str_pass_due == 'collection_bucket_5_to10':
            str_pass_due = 1030510
        elif str_pass_due == 'collection_bucket_11_to25':
            str_pass_due = 1031125
        elif str_pass_due == 'collection_bucket_26_to40':
            str_pass_due = 1032640
        elif str_pass_due == 'collection_bucket_41_to55':
            str_pass_due = 1034155
        elif str_pass_due == 'collection_bucket_56_to70':
            str_pass_due = 1035670
        elif str_pass_due == 'collection_bucket_71_to85':
            str_pass_due = 1037185
        elif str_pass_due == 'collection_bucket_86_to100':
            str_pass_due = 10386100
        elif str_pass_due == 'collection_bucket_101plus':
            str_pass_due = 10310100
        elif str_pass_due == 'collection_supervisor_bucket_1_to4':
            str_pass_due = 1040014
        elif str_pass_due == 'collection_supervisor_bucket_5_to10':
            str_pass_due = 1040510
        elif str_pass_due == 'collection_supervisor_bucket_11_to25':
            str_pass_due = 1041125
        elif str_pass_due == 'collection_supervisor_bucket_26_to40':
            str_pass_due = 1042640
        elif str_pass_due == 'collection_supervisor_bucket_41_to55':
            str_pass_due = 1044155
        elif str_pass_due == 'collection_supervisor_bucket_56_to70':
            str_pass_due = 1045670
        elif str_pass_due == 'collection_supervisor_bucket_71_to85':
            str_pass_due = 1047185
        elif str_pass_due == 'collection_supervisor_bucket_86_to100':
            str_pass_due = 10486100
        elif str_pass_due == 'collection_supervisor_bucket_101plus':
            str_pass_due = 10410100
        elif str_pass_due == 'collection_bucket_ptp_1_to10':
            str_pass_due = 1050110
        elif str_pass_due == 'collection_bucket_ptp_11_to40':
            str_pass_due = 1051140
        elif str_pass_due == 'collection_bucket_ptp_41_to70':
            str_pass_due = 1054170
        elif str_pass_due == 'collection_bucket_ptp_71_to100':
            str_pass_due = 10571100
        elif str_pass_due == 'collection_bucket_ptp_101plus':
            str_pass_due = 10510100
        elif str_pass_due == 'collection_bucket_wa_1_to10':
            str_pass_due = 1060110
        elif str_pass_due == 'collection_bucket_wa_11_to40':
            str_pass_due = 1061140
        elif str_pass_due == 'collection_bucket_wa_41_to70':
            str_pass_due = 1064170
        elif str_pass_due == 'collection_bucket_wa_71_to100':
            str_pass_due = 10671100
        elif str_pass_due == 'collection_bucket_wa_101plus':
            str_pass_due = 10610100
        elif str_pass_due == 'bo_sd_verifier_bucket_1_to4':
            str_pass_due = 1070014
        elif str_pass_due == 'bo_sd_verifier_bucket_5_to10':
            str_pass_due = 1070510
        elif str_pass_due == 'bo_sd_verifier_bucket_11_to25':
            str_pass_due = 1071125
        elif str_pass_due == 'bo_sd_verifier_bucket_26_to40':
            str_pass_due = 1072640
        elif str_pass_due == 'bo_sd_verifier_bucket_41_to55':
            str_pass_due = 1074155
        elif str_pass_due == 'bo_sd_verifier_bucket_56_to70':
            str_pass_due = 1075670
        elif str_pass_due == 'bo_sd_verifier_bucket_71_to85':
            str_pass_due = 1077185
        elif str_pass_due == 'bo_sd_verifier_bucket_86_to100':
            str_pass_due = 10786100
        elif str_pass_due == 'bo_sd_verifier_bucket_101plus':
            str_pass_due = 10710100
        elif str_pass_due == 'collection_supervisor_ptp_1_to10':
            str_pass_due = 1080110
        elif str_pass_due == 'collection_supervisor_ptp_11_to40':
            str_pass_due = 1081140
        elif str_pass_due == 'collection_supervisor_ptp_41_to70':
            str_pass_due = 1084170
        elif str_pass_due == 'collection_supervisor_ptp_71_to100':
            str_pass_due = 10871100
        elif str_pass_due == 'collection_supervisor_ptp_101plus':
            str_pass_due = 10810100
        elif str_pass_due == 'bo_sd_verifier_ptp_1_to10':
            str_pass_due = 1090110
        elif str_pass_due == 'bo_sd_verifier_ptp_11_to40':
            str_pass_due = 1091140
        elif str_pass_due == 'bo_sd_verifier_ptp_41_to70':
            str_pass_due = 1094170
        elif str_pass_due == 'bo_sd_verifier_ptp_71_to100':
            str_pass_due = 10971100
        elif str_pass_due == 'bo_sd_verifier_ptp_101plus':
            str_pass_due = 10910100
        elif str_pass_due == 'collection_supervisor_wa_1_to10':
            str_pass_due = 1100110
        elif str_pass_due == 'collection_supervisor_wa_11_to40':
            str_pass_due = 1101140
        elif str_pass_due == 'collection_supervisor_wa_41_to70':
            str_pass_due = 1104170
        elif str_pass_due == 'collection_supervisor_wa_71_to100':
            str_pass_due = 11071100
        elif str_pass_due == 'collection_supervisor_wa_101plus':
            str_pass_due = 11010100
        elif str_pass_due == 'bo_sd_verifier_wa_1_to10':
            str_pass_due = 1110110
        elif str_pass_due == 'bo_sd_verifier_wa_11_to40':
            str_pass_due = 1111140
        elif str_pass_due == 'bo_sd_verifier_wa_41_to70':
            str_pass_due = 1114170
        elif str_pass_due == 'bo_sd_verifier_wa_71_to100':
            str_pass_due = 11171100
        elif str_pass_due == 'bo_sd_verifier_wa_101plus':
            str_pass_due = 11110100
        elif str_pass_due == 'collection_bucket_ignore_called_41_to70':
            str_pass_due = 1124170
        elif str_pass_due == 'collection_bucket_ignore_called_71_to100':
            str_pass_due = 11271100
        elif str_pass_due == 'collection_bucket_ignore_called_101plus':
            str_pass_due = 11210100
        elif str_pass_due == 'collection_supervisor_ignore_called_41_to70':
            str_pass_due = 1134170
        elif str_pass_due == 'collection_supervisor_ignore_called_71_to100':
            str_pass_due = 11371100
        elif str_pass_due == 'collection_supervisor_ignore_called_101plus':
            str_pass_due = 11310100
        elif str_pass_due == 'bo_sd_verifier_ignore_called_41_to70':
            str_pass_due = 1144170
        elif str_pass_due == 'bo_sd_verifier_ignore_called_71_to100':
            str_pass_due = 11471100
        elif str_pass_due == 'bo_sd_verifier_ignore_called_101plus':
            str_pass_due = 11410100
        elif str_pass_due == 'bucket_1_t_minus_5':
            str_pass_due = 11510101
        elif str_pass_due == 'bucket_1_t_minus_3':
            str_pass_due = 11510102
        elif str_pass_due == 'bucket_1_t_minus_1':
            str_pass_due = 11510103
        elif str_pass_due == 'bucket_1_t0':
            str_pass_due = 11510104
        elif str_pass_due == 'collection_bucket_noncontacts_s2':
            str_pass_due = 11600000
        elif str_pass_due == 'collection_bucket_noncontacts_s3':
            str_pass_due = 11700000
        elif str_pass_due == 'collection_bucket_noncontacts_s4':
            str_pass_due = 11800000
        elif str_pass_due == 'collection_bucket_noncontacts_s2_non_agent':
            str_pass_due = 11900000
        elif str_pass_due == 'collection_bucket_noncontacts_s3_non_agent':
            str_pass_due = 12000000
        elif str_pass_due == 'collection_bucket_noncontacts_s4_non_agent':
            str_pass_due = 12100000
        elif str_pass_due == 'collection_bucket_vendor_b2':
            str_pass_due = 12200000
        elif str_pass_due == 'collection_bucket_vendor_b3':
            str_pass_due = 12300000
        elif str_pass_due == 'collection_bucket_vendor_b4':
            str_pass_due = 12400000
        elif str_pass_due == 'collection_bucket_noncontacts_b2':
            str_pass_due = 12500000
        elif str_pass_due == 'collection_bucket_noncontacts_b3':
            str_pass_due = 12600000
        elif str_pass_due == 'collection_bucket_noncontacts_b4':
            str_pass_due = 12700000
        elif str_pass_due == 'collection_bucket_noncontacts_b2_non_agent':
            str_pass_due = 12800000
        elif str_pass_due == 'collection_bucket_noncontacts_b3_non_agent':
            str_pass_due = 12900000
        elif str_pass_due == 'collection_bucket_noncontacts_b4_non_agent':
            str_pass_due = 13000000
        try:
            pass_due_int = int(str_pass_due)
        except Exception as e:
            logger.info({
                'payment_parse_pass_due': str_pass_due,
                'error': 'converting into int',
                'e': e
            })
            return None

        if pass_due_int == 6:
            ret_val = 'T >= -5'
        elif 1 <= pass_due_int <= 5:
            ret_val = "T-%d" % (pass_due_int)
        elif (pass_due_int == 0):
            ret_val = "T 0"
        elif (pass_due_int == -1):
            ret_val = "T > 0"
        elif pass_due_int == 15:
            ret_val = '-5 <= T < 0'
        elif pass_due_int == 531:
            ret_val = 'T-3, T-1'
        elif pass_due_int == 14:
            ret_val = 'T+1, T+4'
        elif pass_due_int == 530:
            ret_val = 'T+5, T+29'
        elif pass_due_int == 30:
            ret_val = 'T+29 >> ++'
        elif pass_due_int == 1000:
            ret_val = 'T not Called'
        elif pass_due_int == 1001:
            ret_val = 'T 0 (to be called)'
        elif pass_due_int == 1002:
            ret_val = 'T++ GRAB'
        elif pass_due_int == 1003:
            ret_val = 'T<=0 Whatsapp'
        elif pass_due_int == 10014:
            ret_val = 'Collection agent T+1, T+4'
        elif pass_due_int == 100515:
            ret_val = 'Collection agent T+5, T+15'
        elif pass_due_int == 1001629:
            ret_val = 'Collection agent T+16, T+29'
        elif pass_due_int == 1003044:
            ret_val = 'Collection agent T+30, T+44'
        elif pass_due_int == 1004559:
            ret_val = 'Collection agent T+45, T+59'
        elif pass_due_int == 1006074:
            ret_val = 'Collection agent T+60, T+74'
        elif pass_due_int == 1007589:
            ret_val = 'Collection agent T+75, T+89'
        elif pass_due_int == 10090119:
            ret_val = 'Collection agent T+90, T+119'
        elif pass_due_int == 100120179:
            ret_val = 'Collection agent T+120, T+179'
        elif pass_due_int == 111180:
            ret_val = 'Collection agent T+180 >> ++'
        elif pass_due_int == 1000001:
            ret_val = 'Collection agent 2 PTP'
        elif pass_due_int == 1000002:
            ret_val = 'Collection agent 3 PTP'
        elif pass_due_int == 1000003:
            ret_val = 'Collection agent 3 ignore called'
        elif pass_due_int == 1000004:
            ret_val = 'Collection agent 2 whatsapp'
        elif pass_due_int == 1000005:
            ret_val = 'Collection agent 3 whatsapp'
        elif pass_due_int == 1000006:
            ret_val = 'Collection agent 4 PTP'
        elif pass_due_int == 1000007:
            ret_val = 'Collection agent 5 PTP'
        elif pass_due_int == 1000008:
            ret_val = 'Collection agent 4 whatsapp'
        elif pass_due_int == 1000009:
            ret_val = 'Collection agent 5 whatsapp'
        elif pass_due_int == 1000010:
            ret_val = 'Collection agent 4 ignore called'
        elif pass_due_int == 1000011:
            ret_val = 'Collection agent 5 ignore called'
        elif pass_due_int == 10214:
            ret_val = 'Collection supervisor T+1, T+4'
        elif pass_due_int == 102515:
            ret_val = 'Collection supervisor T+5, T+15'
        elif pass_due_int == 1021629:
            ret_val = 'Collection supervisor T+16, T+29'
        elif pass_due_int == 1023044:
            ret_val = 'Collection supervisor T+30, T+44'
        elif pass_due_int == 1024559:
            ret_val = 'Collection supervisor T+45, T+59'
        elif pass_due_int == 1026074:
            ret_val = 'Collection supervisor T+60, T+74'
        elif pass_due_int == 1027589:
            ret_val = 'Collection supervisor T+75, T+89'
        elif pass_due_int == 10290119:
            ret_val = 'Collection supervisor T+90, T+119'
        elif pass_due_int == 102120179:
            ret_val = 'Collection supervisor T+120, T+179'
        elif pass_due_int == 112180:
            ret_val = 'Collection supervisor T+180 >> ++'
        elif str_pass_due == 112101:
            ret_val = 'Collection supervisor T+90 >> ++'
        elif pass_due_int == 1020001:
            ret_val = 'Collection supervisor PTP'
        elif pass_due_int == 1020002:
            ret_val = 'Collection supervisor ignore called'
        elif pass_due_int == 1020003:
            ret_val = 'Collection supervisor whatsapp'
        elif pass_due_int == 1030014:
            ret_val = 'Collection bucket T+1, T+4'
        elif pass_due_int == 1030510:
            ret_val = 'Collection bucket T+5, T+10'
        elif pass_due_int == 1031125:
            ret_val = 'Collection bucket T+11, T+25'
        elif pass_due_int == 1032640:
            ret_val = 'Collection bucket T+26, T+40'
        elif pass_due_int == 1034155:
            ret_val = 'Collection bucket T+41, T+55'
        elif pass_due_int == 1035670:
            ret_val = 'Collection bucket T+56, T+70'
        elif pass_due_int == 1037185:
            ret_val = 'Collection bucket T+71, T+85'
        elif pass_due_int == 10386100:
            ret_val = 'Collection bucket T+86, T+100'
        elif pass_due_int == 10310100:
            ret_val = 'Collection bucket T+101 ++'
        elif pass_due_int == 1040014:
            ret_val = 'Collection Supervisor bucket T+1, T+4'
        elif pass_due_int == 1040510:
            ret_val = 'Collection Supervisor bucket T+5, T+10'
        elif pass_due_int == 1041125:
            ret_val = 'Collection Supervisor bucket T+11, T+25'
        elif pass_due_int == 1042640:
            ret_val = 'Collection Supervisor bucket T+26, T+40'
        elif pass_due_int == 1044155:
            ret_val = 'Collection Supervisor bucket T+41, T+55'
        elif pass_due_int == 1045670:
            ret_val = 'Collection Supervisor bucket T+56, T+70'
        elif pass_due_int == 1047185:
            ret_val = 'Collection Supervisor bucket T+71, T+85'
        elif pass_due_int == 10486100:
            ret_val = 'Collection Supervisor bucket T+86, T+90'
        elif pass_due_int == 10410100:
            ret_val = 'Collection Supervisor bucket T+101 ++'
        elif pass_due_int == 1050110:
            ret_val = 'Collection bucket 1 PTP'
        elif pass_due_int == 1051140:
            ret_val = 'Collection bucket 2 PTP'
        elif pass_due_int == 1054170:
            ret_val = 'Collection bucket 3 PTP'
        elif pass_due_int == 10571100:
            ret_val = 'Collection bucket 4 PTP'
        elif pass_due_int == 10510100:
            ret_val = 'Collection bucket 5 PTP'
        elif pass_due_int == 1060110:
            ret_val = 'Collection bucket 1 WA'
        elif pass_due_int == 1061140:
            ret_val = 'Collection bucket 2 WA'
        elif pass_due_int == 1064170:
            ret_val = 'Collection bucket 3 WA'
        elif pass_due_int == 10671100:
            ret_val = 'Collection bucket 4 WA'
        elif pass_due_int == 10610100:
            ret_val = 'Collection bucket 5 WA'
        elif pass_due_int == 1070014:
            ret_val = 'T+1, T+4'
        elif pass_due_int == 1070510:
            ret_val = 'T+5, T+10'
        elif pass_due_int == 1071125:
            ret_val = 'T+11, T+25'
        elif pass_due_int == 1072640:
            ret_val = 'T+26, T+40'
        elif pass_due_int == 1074155:
            ret_val = 'T+41, T+55'
        elif pass_due_int == 1075670:
            ret_val = 'T+56, T+70'
        elif pass_due_int == 1077185:
            ret_val = 'T+71, T+85'
        elif pass_due_int == 10786100:
            ret_val = 'T+86, T+90'
        elif pass_due_int == 10710100:
            ret_val = 'T+90 ++'
        elif pass_due_int == 1080110:
            ret_val = 'Collection Supervisor bucket 1 PTP'
        elif pass_due_int == 1081140:
            ret_val = 'Collection Supervisor bucket 2 PTP'
        elif pass_due_int == 1084170:
            ret_val = 'Collection Supervisor bucket 3 PTP'
        elif pass_due_int == 10871100:
            ret_val = 'Collection Supervisor bucket 4 PTP'
        elif pass_due_int == 10810100:
            ret_val = 'Collection Supervisor bucket 5 PTP'
        elif pass_due_int == 1090110:
            ret_val = 'Bucket 1 PTP'
        elif pass_due_int == 1091140:
            ret_val = 'Bucket 2 PTP'
        elif pass_due_int == 1094170:
            ret_val = 'Bucket 3 PTP'
        elif pass_due_int == 10971100:
            ret_val = 'Bucket 4 PTP'
        elif pass_due_int == 10910100:
            ret_val = 'Bucket 5 PTP'
        elif pass_due_int == 1100110:
            ret_val = 'Collection Supervisor bucket 1 WA'
        elif pass_due_int == 1101140:
            ret_val = 'Collection Supervisor bucket 2 WA'
        elif pass_due_int == 1104170:
            ret_val = 'Collection Supervisor bucket 3 WA'
        elif pass_due_int == 11071100:
            ret_val = 'Collection Supervisor bucket 4 WA'
        elif pass_due_int == 11010100:
            ret_val = 'Collection Supervisor bucket 5 WA'
        elif pass_due_int == 1110110:
            ret_val = 'Bucket 1 WA'
        elif pass_due_int == 1111140:
            ret_val = 'Bucket 2 WA'
        elif pass_due_int == 1114170:
            ret_val = 'Bucket 3 WA'
        elif pass_due_int == 11171100:
            ret_val = 'Bucket 4 WA'
        elif pass_due_int == 11110100:
            ret_val = 'Bucket 5 WA'
        elif pass_due_int == 1124170:
            ret_val = 'Collection Bucket 3 Ignore Called'
        elif pass_due_int == 11271100:
            ret_val = 'Collection Bucket 4 Ignore Called'
        elif pass_due_int == 11210100:
            ret_val = 'Collection Bucket 5 Ignore Called'
        elif pass_due_int == 1134170:
            ret_val = 'Collection Supervisor Bucket 3 Ignore Called'
        elif pass_due_int == 11371100:
            ret_val = 'Collection Supervisor Bucket 4 Ignore Called'
        elif pass_due_int == 11310100:
            ret_val = 'Collection Supervisor Bucket 5 Ignore Called'
        elif pass_due_int == 1144170:
            ret_val = 'Bucket 3 Ignore Called'
        elif pass_due_int == 11471100:
            ret_val = 'Bucket 4 Ignore Called'
        elif pass_due_int == 11410100:
            ret_val = 'Bucket 5 Ignore Called'
        elif pass_due_int == 11510101:
            ret_val = 'Collection Bucket 1 T-5'
        elif pass_due_int == 11510102:
            ret_val = 'Collection Bucket 1 T-3'
        elif pass_due_int == 11510103:
            ret_val = 'Collection Bucket 1 T-1'
        elif pass_due_int == 11510104:
            ret_val = 'Collection Bucket 1 T0'
        elif pass_due_int == 11600000:
            ret_val = 'Collection Bucket 2 NonContacts Squad'
        elif pass_due_int == 11700000:
            ret_val = 'Collection Bucket 3 NonContacts Squad'
        elif pass_due_int == 11800000:
            ret_val = 'Collection Bucket 4 NonContacts Squad'
        elif pass_due_int == 11900000:
            ret_val = 'Bucket 2 NonContacts Non Agent Squad'
        elif pass_due_int == 12000000:
            ret_val = 'Bucket 3 NonContacts Non Agent Squad'
        elif pass_due_int == 12100000:
            ret_val = 'Bucket 4 NonContacts Non Agent Squad'
        elif pass_due_int == 12200000:
            ret_val = 'Bucket 2 Vendor'
        elif pass_due_int == 12300000:
            ret_val = 'Bucket 3 Vendor'
        elif pass_due_int == 12400000:
            ret_val = 'Bucket 4 Vendor'
        elif pass_due_int == 12500000:
            ret_val = 'Bucket 2 NonContacts'
        elif pass_due_int == 12600000:
            ret_val = 'Bucket 3 NonContacts'
        elif pass_due_int == 12700000:
            ret_val = 'Bucket 4 NonContacts'
        elif pass_due_int == 12800000:
            ret_val = 'Bucket 2 NonContacts Non Agent'
        elif pass_due_int == 12900000:
            ret_val = 'Bucket 3 NonContacts Non Agent'
        elif pass_due_int == 13000000:
            ret_val = 'Bucket 4 NonContacts Non Agent'
        else:
            ret_val = ''

        return [pass_due_int, ret_val]


def payment_filter_search_field(keyword):
    from django.core.validators import validate_email
    from django.core.validators import ValidationError
    from juloserver.julo.models import Partner
    from juloserver.julo.statuses import PaymentStatusCodes
    from juloserver.julo.services2.payment_method import search_payments_base_on_virtual_account

    keyword = keyword.strip()
    if keyword[:1] == '+':
        keyword = keyword[1:]
    if not keyword.isdigit():
        try:
            validate_email(keyword)
            is_email_valid = True
        except ValidationError:
            is_email_valid = False
        if is_email_valid:
            return 'loan__application__email', keyword
        partner = Partner.objects.filter(name=keyword).only('id').first()
        if partner:
            return 'loan__application__partner', partner
        return 'loan__application__fullname', keyword
    if len(keyword) >= 10:
        is_virtual_account, va_customer_ids = search_payments_base_on_virtual_account(
            keyword
        )
        if is_virtual_account:
            return 'loan__customer_id', va_customer_ids
    if len(keyword) == 16:
        return 'loan__application__ktp', keyword
    if len(keyword) == 10:
        if keyword[:1] == '2':
            return 'loan__application__id', keyword
        if keyword[:1] == '3':
            return 'loan__id', keyword
        if keyword[:1] == '4':
            return 'id', keyword
    if len(keyword) == 3 and keyword[:1] == '3' and int(keyword) in PaymentStatusCodes.all():
        return 'payment_status__status_code', keyword

    mobile_phone_regex = re.compile(r'^(^\+62\s?|^62\s?|^0)(\d{3,4}-?){2}\d{3,4}$')
    if mobile_phone_regex.match(keyword):
        return 'loan__application__mobile_phone_1', keyword
    return None, keyword


def account_payment_filter_search_field(keyword):
    from django.core.validators import validate_email
    from django.core.validators import ValidationError
    from juloserver.julo.models import Partner
    from juloserver.julo.statuses import PaymentStatusCodes, JuloOneCodes

    keyword = keyword.strip()
    if keyword[:1] == '+':
        keyword = keyword[1:]
    if keyword.isdigit():
        if len(keyword) == 3:
            account_payment = AccountPayment.objects.filter(id=keyword)
            if account_payment:
                return 'id', keyword
            if keyword[:1] == '3' and int(keyword) in PaymentStatusCodes.all():
                return 'status__status_code', keyword
            elif keyword[:1] == '4' and int(keyword) in JuloOneCodes.all():
                return 'account__status__status_code', keyword
            else:
                return None, keyword
        elif len(keyword) == 10:
            if keyword[:1] == '2':
                account_ids = Application.objects.filter(account__isnull=False, id__contains=keyword). \
                    values_list('account_id')

                return 'account__id', account_ids
            elif keyword[:1] == '5':
                return 'id', keyword
            elif keyword[:1] == '7':
                return 'account__id', keyword
            else:
                return None, keyword
        elif len(keyword) == 16:
            account_ids = Application.objects.filter(account__isnull=False, ktp__contains=keyword). \
                values_list('account_id')
            return 'account__id', account_ids
        else:
            mobile_phone_regex = re.compile(r'^(^\+62\s?|^62\s?|^0)(\d{3,4}-?){2}\d{3,4}$')
            if mobile_phone_regex.match(keyword):
                account_ids = Application.objects.filter(account__isnull=False, mobile_phone_1__contains=keyword). \
                    values_list('account_id')
                return 'account__id', account_ids
            else:
                account_payment = AccountPayment.objects.filter(id=keyword)
                if account_payment:
                    return 'id', keyword
                return None, keyword
    else:
        try:
            validate_email(keyword)
            is_email_valid = True
        except ValidationError:
            is_email_valid = False
        if is_email_valid:
            return 'account__customer__email', keyword
        else:
            product_lines = ProductLine.objects.filter(product_line_type__icontains=keyword)
            if product_lines:
                account_ids = Application.objects.filter(account__isnull=False, product_line__in=product_lines). \
                    values_list('account_id')
                return 'account__id', account_ids
            partner_list = Partner.objects.filter(name__icontains=keyword)
            if partner_list:
                account_ids = Application.objects.filter(account__isnull=False,
                                                         partner__in=partner_list).\
                    values_list('account_id')
                return 'account__id', account_ids
            else:
                account_ids = Application.objects.filter(account__isnull=False, fullname__icontains=keyword). \
                    values_list('account_id')
                return 'account__id', account_ids
                # return 'account__customer__fullname', keyword


def get_ptp_max_due_date(loan):
    oldest_unpaid_payment = loan.get_oldest_unpaid_payment()

    if oldest_unpaid_payment is None:
        return None

    today = timezone.localtime(timezone.now()).date()
    due_date = oldest_unpaid_payment.due_date
    dpd = (today - due_date).days

    max_bucket1_ptp = due_date + relativedelta(days=BucketConst.BUCKET_1_DPD['to'])
    max_bucket2_ptp = due_date + relativedelta(days=BucketConst.BUCKET_2_DPD['to'])
    max_bucket3_ptp = due_date + relativedelta(days=BucketConst.BUCKET_3_DPD['to'])
    max_bucket4_ptp = due_date + relativedelta(days=BucketConst.BUCKET_4_DPD['to'])
    max_bucket5_ptp = date(2017, 1, 1)

    if BucketConst.BUCKET_1_DPD['from'] <= dpd <= BucketConst.BUCKET_1_DPD['to']:
        return max_bucket1_ptp
    elif BucketConst.BUCKET_2_DPD['from'] <= dpd <= BucketConst.BUCKET_2_DPD['to']:
        return max_bucket2_ptp
    elif BucketConst.BUCKET_3_DPD['from'] <= dpd <= BucketConst.BUCKET_3_DPD['to']:
        return max_bucket3_ptp
    elif BucketConst.BUCKET_4_DPD['from'] <= dpd <= BucketConst.BUCKET_4_DPD['to']:
        return max_bucket4_ptp
    elif BucketConst.BUCKET_5_DPD <= dpd:
        return max_bucket5_ptp
    else:
        return None


def get_ptp_max_due_date_for_j1(account):
    oldest_unpaid_account_payment = account.get_oldest_unpaid_account_payment()

    if oldest_unpaid_account_payment is None:
        return None

    today = timezone.localtime(timezone.now()).date()
    due_date = oldest_unpaid_account_payment.due_date
    dpd = (today - due_date).days

    max_bucket1_ptp = due_date + relativedelta(days=BucketConst.BUCKET_1_DPD['to'])
    max_bucket2_ptp = due_date + relativedelta(days=BucketConst.BUCKET_2_DPD['to'])
    max_bucket_3_and_4_ptp = due_date + relativedelta(days=BucketConst.BUCKET_4_DPD['to'])
    max_bucket5_ptp = date(2017, 1, 1)

    if BucketConst.BUCKET_1_DPD['from'] <= dpd <= BucketConst.BUCKET_1_DPD['to']:
        return max_bucket1_ptp
    elif BucketConst.BUCKET_2_DPD['from'] <= dpd <= BucketConst.BUCKET_2_DPD['to']:
        return max_bucket2_ptp
    elif BucketConst.BUCKET_3_DPD['from'] <= dpd <= BucketConst.BUCKET_4_DPD['to']:
        return max_bucket_3_and_4_ptp
    elif BucketConst.BUCKET_5_DPD <= dpd:
        return max_bucket5_ptp
    else:
        return None

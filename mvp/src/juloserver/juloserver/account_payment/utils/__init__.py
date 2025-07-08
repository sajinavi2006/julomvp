from juloserver.julo.statuses import PaymentStatusCodes
import random
import pytz
from datetime import datetime, time
from django.utils import timezone


def get_account_payment_status_based_on_dpd(dpd):
    if dpd < -3:
        return PaymentStatusCodes.PAYMENT_NOT_DUE
    elif dpd < -1:
        return PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS
    elif dpd < 0:
        return PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS
    elif dpd == 0:
        return PaymentStatusCodes.PAYMENT_DUE_TODAY
    elif dpd < 5:
        return PaymentStatusCodes.PAYMENT_1DPD
    elif dpd < 30:
        return PaymentStatusCodes.PAYMENT_5DPD
    elif dpd < 60:
        return PaymentStatusCodes.PAYMENT_30DPD
    elif dpd < 90:
        return PaymentStatusCodes.PAYMENT_60DPD
    elif dpd < 120:
        return PaymentStatusCodes.PAYMENT_90DPD
    elif dpd < 150:
        return PaymentStatusCodes.PAYMENT_120DPD
    elif dpd < 180:
        return PaymentStatusCodes.PAYMENT_150DPD
    elif dpd >= 180:
        return PaymentStatusCodes.PAYMENT_180DPD


def generate_checkout_xid():
    # exclude lowecase, O, 0 on generate xid
    checkout_xid = ''.join(
        random.choice('ABCDEFGHIJKLMNPQRSTUVWXYZ' + '123456789')
        for _ in range(9))

    return checkout_xid


def get_expired_date_checkout_request():
    tz = pytz.timezone("Asia/Jakarta")
    expired_date = tz.localize(datetime.combine(timezone.localtime(timezone.now()).date(),
                               time(23, 59, 59, 999999)))

    return expired_date

from __future__ import print_function
from future import standard_library
standard_library.install_aliases()
import urllib.request, urllib.parse, urllib.error

from django.contrib.auth.decorators import user_passes_test

from .models import PaymentLocked, PaymentLockedMaster

from juloserver.account_payment.models import AccountPayment


MAX_COUNT_LOCK_PAYMENT = 9999


def role_allowed(user_obj, arr_group):
    return user_obj.groups.filter(name__in=arr_group).exists()


def check_lock_payment(payment_obj, user_obj):
    if not payment_obj:
        return

    payment_locked_master = PaymentLockedMaster.objects.get_or_none(payment_id=payment_obj.id)

    if not payment_locked_master:
        return 3, None

    payment_locked_obj = PaymentLocked.objects.filter(
        payment_id=payment_obj.id,
        status_obsolete=False,
        locked=True)

    if payment_locked_obj.filter(user_lock_id=user_obj.id).count() >= 1:
        return 1, payment_locked_obj

    else:
        if payment_locked_obj.count() >= 1:
            return 2, payment_locked_obj
        else:
            return 3, None


def get_user_lock_count(current_user):
    return PaymentLocked.objects.filter(user_lock=current_user,
                locked=True).count()


def get_payment_lock_count(payment_obj):
    return PaymentLocked.objects.filter(payment=payment_obj,
                locked=True).count()


def get_account_payment_lock_count(payment_obj):
    return AccountPayment.objects.filter(pk=payment_obj.pk, is_locked=True).count()


def payment_lock_list():
    payment_lock_queryset = PaymentLocked.objects.select_related('payment').filter(
        locked=True).order_by('payment__id').values_list('payment_id', flat=True)
    payment_id_locked = list(payment_lock_queryset)
    return payment_id_locked


def lock_by_user(queryset):
    lock_by = ''
    index = 0
    for item in queryset.iterator():
        if index == 0:
            lock_by += "%s" % item.user_lock
        else:
            lock_by += ", %s" % item.user_lock
        index += 1
    return lock_by


def get_lock_status(payment_obj, user_obj):
    lock_status = 1
    lock_by = None
    ret_cek_app = check_lock_payment(payment_obj, user_obj)
    if ret_cek_app[0] == 1:
        lock_status = 0
        lock_by = lock_by_user(ret_cek_app[1])
    elif ret_cek_app[0] == 2:
        lock_status = 1
        lock_by = lock_by_user(ret_cek_app[1])

    if payment_obj.due_late_days < -5:
        lock_status = 0

    # Force if admin full locked status is False
    if role_allowed(user_obj, ['admin_unlocker']):
        lock_status = 0

    # print "lock_status, lock_by: ", lock_status, lock_by
    return lock_status, lock_by

def get_act_pmt_lock_status(payment_obj, user_obj):
    return 1 if payment_obj.is_locked else 0, payment_obj.locked_by

def unlocked_payment(payment_locked_obj, user_unlock_obj, status_to=None):
    payment_locked = payment_locked_obj
    if payment_locked:
        payment_locked.locked = False
        payment_locked.user_unlock = user_unlock_obj
        if status_to:
            payment_locked.status_code_unlocked = status_to

        payment_locked.save()
        return payment_locked


def unlocked_app_from_user(app_obj, user_obj, status_to=None):
    app_locked = ApplicationLocked.objects.get_or_none(application=app_obj,
                            user_lock=user_obj,
                            locked=True)
    print("app_locked: ", app_locked)
    if app_locked:
        if status_to:
            return unlocked_app(app_locked, user_obj, status_to)
        else:
            return unlocked_app(app_locked, user_obj)

    return None


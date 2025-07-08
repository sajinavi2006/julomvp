from __future__ import absolute_import

import json
from builtins import str
from datetime import datetime

from juloserver.julo.banks import BankCodes
from juloserver.julo.models import PaymentMethod, VirtualAccountSuffix
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.utils import format_mobile_phone
from juloserver.julo.services import handle_notify_moengage_after_payment_method_change

from .models import CRMBucketStatusColor


def load_color():
    status_color = CRMBucketStatusColor.objects.all()
    status_color_index = {}
    for status in status_color:
        status_color_index[str(status.status_code)] = {
            'color': status.color.color,
            'display_text': status.color.display_text,
            'content_color': status.color.content_color,
        }
    return status_color_index


def update_primary_and_is_shown_payment_methods(data, account, payment_methods):
    is_primary_j1_payment_method_id = data['is_primary_j1_payment_method_id'].strip()
    is_shown_j1_payment_methods_id = json.loads(data['is_shown_j1_payment_methods_id'])
    payment_methods.update(is_primary=False, is_shown=False, udate=datetime.now(), is_affected=True)

    PaymentMethod.objects.filter(id__in=is_shown_j1_payment_methods_id).update(
        is_primary=False, is_shown=True, udate=datetime.now(), is_affected=True
    )
    PaymentMethod.objects.filter(id=is_primary_j1_payment_method_id).update(
        is_primary=True, is_shown=True, udate=datetime.now(), is_affected=True
    )

    payment_methods = account.customer.paymentmethod_set.all()
    for pm in payment_methods:
        handle_notify_moengage_after_payment_method_change(pm)

    return payment_methods


def generate_va_for_bank_bca(mobile_phone_1, account, sequence):
    mobile_phone_1 = format_mobile_phone(mobile_phone_1)
    va_suffix = mobile_phone_1
    virtual_account = "".join(['10994', va_suffix])
    PaymentMethod.objects.create(
        payment_method_code='10994',
        payment_method_name='Bank BCA',
        bank_code=BankCodes.BCA,
        customer=account.customer,
        is_shown=True,
        is_primary=False,
        virtual_account=virtual_account,
        sequence=sequence,
    )
    payment_methods = account.customer.paymentmethod_set.all()
    return payment_methods


def generate_va_for_bank_permata(account, sequence):
    virtual_account_suffix = VirtualAccountSuffix.objects.get_or_none(account=account)
    payment_methods = []
    if not virtual_account_suffix:
        va_suffix_obj = (
            VirtualAccountSuffix.objects.filter(loan=None, line_of_credit=None, account=None)
            .order_by('id')
            .first()
        )
        if not va_suffix_obj:
            return payment_methods
        else:
            va_suffix_obj.account = account
            va_suffix_obj.save()
            virtual_account_suffix = va_suffix_obj
    virtual_account = "".join(
        [PaymentMethodCodes.PERMATA, virtual_account_suffix.virtual_account_suffix]
    )
    PaymentMethod.objects.create(
        payment_method_code=PaymentMethodCodes.PERMATA,
        payment_method_name='Bank PERMATA',
        bank_code=BankCodes.PERMATA,
        customer=account.customer,
        is_shown=True,
        is_primary=False,
        virtual_account=virtual_account,
        sequence=sequence,
    )
    payment_methods = account.customer.paymentmethod_set.all()
    return payment_methods


def list_payment_methods(payment_methods):
    list_payment_methods = [
        {
            'id': payment_method.id,
            'name': payment_method.payment_method_name,
            'code': payment_method.bank_code,
            'va': payment_method.virtual_account,
            'is_primary': payment_method.is_primary,
            'is_shown': payment_method.is_shown,
        }
        for payment_method in payment_methods
    ]
    return list_payment_methods

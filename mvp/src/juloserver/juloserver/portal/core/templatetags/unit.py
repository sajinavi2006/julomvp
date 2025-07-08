from __future__ import division

import os
from builtins import str
from datetime import datetime

from babel.dates import format_date
from babel.numbers import format_decimal
from core.functions import display_name
from django import template
from django.utils import timezone
from past.utils import old_div
from juloserver.julo.models import Image

from juloserver.apiv2.models import AutoDataCheck
from juloserver.apiv2.services import false_reject_min_exp
from juloserver.cashback.constants import CashbackChangeReason
from juloserver.julo.constants import FalseRejectMiniConst
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.streamlined_communication.constant import ImageType
from juloserver.julo.utils import convert_number_to_rupiah_terbilang

register = template.Library()


@register.filter(is_safe=True, name='show_filename')
def show_filename(value):
    filename = os.path.basename(value)
    if filename:
        return filename
    else:
        return '-'


@register.filter(is_safe=True, name='f_rupiahs')
def format_rupiahs(rupiahs, arg):
    if rupiahs:
        if arg == 'yes':
            return "Rp %s.00,-" % (format_decimal(rupiahs, locale='id_ID'))
        elif arg == 'no_currency':
            return "%s" % (format_decimal(rupiahs, locale='id_ID'))
        else:
            return "Rp %s" % (format_decimal(rupiahs, locale='id_ID'))
    else:
        if arg == "default-0":
            return "Rp 0"
        return '-'


@register.filter(name='display_safe')
def display_safe(field):
    return display_name(field)


@register.filter(name='display_img_status')
def display_img_status(field):
    """
    (DELETED, 'Deleted'),
    (CURRENT, 'Current'),
    (RESUBMISSION_REQ, 'Resubmission Required')
    """
    if field == 0:
        return "Normal"
    elif field == -1:
        return "Tidak Terpakai"
    else:
        return "Butuh Dikirim Ulang"


@register.filter(name='bapak_or_ibu')
def bapak_or_ibu(field):
    if field:
        field_check = field.lower()
        if (
            field_check == 'p'
            or field_check == 'pria'
            or field_check == 'l'
            or field_check == 'laki'
        ):
            return 'bapak'.title()
        else:
            return 'ibu'.title()


@register.filter(name='pak_or_bu')
def pak_or_bu(field):
    if field:
        field_check = field.lower()
        if (
            field_check == 'p'
            or field_check == 'pria'
            or field_check == 'l'
            or field_check == 'laki'
        ):
            return 'pak'.title()
        else:
            return 'bu'.title()


@register.filter(name='bapak_or_ibu_lower')
def bapak_or_ibu_lower(field):
    if field:
        field_check = field.lower()
        if (
            field_check == 'p'
            or field_check == 'pria'
            or field_check == 'l'
            or field_check == 'laki'
        ):
            return 'bapak'
        else:
            return 'ibu'


@register.filter(is_safe=True, name='f_rupiahs_percent')
def f_rupiahs_percent(rupiahs, arg):
    if rupiahs:
        if arg == '':
            return format_rupiahs(rupiahs, 'no')
        else:
            ret = '{0:.2f}'.format((old_div((float(arg) * float(rupiahs)), 100)))
            return format_rupiahs(ret, 'no')
    else:
        return '-'


@register.filter(is_safe="true", name='f_num_to_written_rupiah')
def f_convert_number_to_rupiah_terbilang(number):
    return convert_number_to_rupiah_terbilang(number)


@register.filter(is_safe=True, name='no_ktp')
def no_ktp(field):
    if field:
        try:
            return "%s.%s.%s.%s.%s" % (field[:2], field[2:4], field[4:6], field[6:12], field[12:])
        except Exception:
            return '-'
    else:
        return '-'


@register.filter(is_safe=True, name='no_hp')
def no_hp(field):
    if field:
        try:
            field_here = str(field).replace(" ", '')
            return "%s %s %s" % (field_here[:4], field_here[4:8], field_here[8:])
        except Exception:
            return '-'
    else:
        return '-'


@register.filter(is_safe=True, name='phone')
def phone(field):
    if field:
        try:
            field_here = str(field).replace(" ", '')
            field_here = str(field_here).replace("+62", '0')
            return "%s" % (field_here)
        except Exception:
            return '-'
    else:
        return '-'


@register.filter(is_safe=True, name='age')
def age(field, d=None):
    if d is None:
        d = datetime.now()
    try:
        ret_val = (d.year - field.year) - int((d.month, d.day) < (field.month, field.day))
    except Exception:
        ret_val = ''
    return ret_val


@register.filter(is_safe=True, name='verification_option')
def verification_option(field, option_list):
    if field:
        ret_val = option_list[field][1]
    else:
        ret_val = 'Blum di Cek'
    return ret_val


@register.filter(is_safe=True, name='f_rupiahs_cek')
def f_rupiahs_cek(rupiahs):
    if rupiahs:
        return format_rupiahs(rupiahs, 'no')
    else:
        return 'Blum di Cek'


@register.filter(is_safe=True, name='percentage_100')
def percentage_100(value):
    if value:
        return "%s" % (value * 100)
    else:
        return '-'


@register.filter(is_safe=True, name='remove_quotes')
def remove_quotes(str):
    if str:
        return str.replace("'", " ")
    else:
        return ''


@register.filter(is_safe=True, name='ca_checklist')
def ca_checklist(value):
    if value is False:
        return 'fa-window-close-o red'
    elif value is None:
        return 'fa-square-o'
    elif value is True:
        return 'fa-check-square-o green'


@register.filter(is_safe=True, name='ca_comment')
def ca_comment(value):
    if value:
        return 'fa-commenting-o'
    else:
        return 'fa-comment-o'


@register.filter(is_safe=True, name='ca_class')
def ca_class(value):
    result = 'ca-' + value
    return result


@register.filter(is_safe=True, name='ca_tr_class')
def ca_tr_class(value):
    str_list = ' '.join(value)
    return str_list.replace(",", " ")


@register.filter(is_safe=True, name='ca_cek_group')
def ca_cek_group(objs, args):
    result = False
    if objs and not None:
        for obj in objs:
            if obj['group_name'] == args:
                result = True
    return result


@register.filter(is_safe=True, name='ca_get_group')
def ca_get_group(objs, args):
    if objs and not None:
        for obj in objs:
            if obj['group_name'] == args:
                return obj


@register.filter(is_safe=True, name='validate_group')
def validate_group(objs, args):
    if objs:
        for obj in objs:
            if obj.name == args:
                return True
    return False


@register.filter(is_safe=True, name='validate_group_prefix')
def validate_group_prefix(objs, args):
    if objs:
        for obj in objs:
            if args in obj.name:
                return True
    return False


@register.filter(is_safe=True, name='upper')
def upper(value):
    return value.upper()


@register.filter(is_safe=True, name='length')
def length(value):
    if value:
        return len(value)
    else:
        return ""


@register.filter(is_safe=True, name='breakjs')
def breakjs(value):
    return value.replace('\n', '<br>')


@register.filter(is_safe=True, name='date_slice')
def date_slice(value):
    return value[0:19]


@register.filter(is_safe=True, name='robo_class')
def robo_class(value):
    now = timezone.localtime(timezone.now())
    hour = now.hour
    if hour > 9 and hour < 13:
        if value is None or value is False:
            return 'btn-warning'
    elif hour > 12:
        if value is None or value is False:
            return 'btn-danger'

    if value is None:
        return 'btn-default'
    elif value is False:
        return 'btn-danger'
    elif value is True:
        return 'btn-success'


@register.filter(is_safe=True, name='email_fil1')
def email_fil1(value):
    if value:
        return value.split(',')


@register.filter(is_safe=True, name='get_credit_score')
def get_credit_score(creditscore):
    if creditscore:
        if false_reject_min_exp(creditscore.application):
            return FalseRejectMiniConst.SCORE
        return creditscore.score


@register.filter(is_safe=True, name='get_credit_score_reason')
def get_credit_score_reason(creditscore):
    if creditscore:
        if false_reject_min_exp(creditscore.application):
            return FalseRejectMiniConst.MESSAGE
        if creditscore.score.lower() in ["c", "--"]:
            desc_list = AutoDataCheck.objects.filter(
                application_id=creditscore.application_id, is_okay=False
            )
            if desc_list:
                return ", ".join([x.data_to_check for x in desc_list])
            else:
                return creditscore.score_tag
        else:
            return creditscore.message


@register.filter(is_safe=True, name='tick')
def tick(value):
    if value:
        return 'fa-check-square-o'
    else:
        return 'fa-times'


@register.filter(is_safe=True, name='subtract')
def subtract(value, arg):
    return value - arg


@register.filter(is_safe=True, name='cshbk_class1')
def cshbk_class1(value, arg):
    if arg == "accruing":
        if value in [
            "loan_initial",
            "payment_on_time",
            CashbackChangeReason.CASHBACK_OVER_PAID,
            "sepulsa_refund",
        ]:
            return "green"
        elif value in ["used_on_payment", "paid_back_to_customer", "sepulsa_purchase"]:
            return "red"
        else:
            return "default"
    elif arg == "balance":
        if value in ["loan_paid_off", CashbackChangeReason.CASHBACK_OVER_PAID, "sepulsa_refund"]:
            return "green"
        elif value in ["used_on_payment", "paid_back_to_customer", "sepulsa_purchase"]:
            return "red"
        else:
            return "default"
    else:
        return "default"


@register.filter(is_safe=True, name='month_and_year')
def month_and_year(dt):
    return dt.strftime("%m/%Y")


@register.filter(is_safe=True, name='count_days')
def count_days(date):
    today = timezone.localtime(timezone.now()).date()
    return (today - date).days


@register.filter(is_safe=True, name='convert_datetime_to_string')
def convert_datetime_to_string(dt):
    return format_date(dt.date(), 'dd MMMM yyyy', locale='id_ID')


@register.filter(is_safe=True, name='get_account_paid_status')
def get_account_paid_status(status_code):
    paid_statuses = [
        PaymentStatusCodes.PAID_ON_TIME,
        PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
        PaymentStatusCodes.PAID_LATE,
    ]
    return 'Ya' if status_code in paid_statuses else 'Tidak'


@register.filter(is_safe=True, name='convert_date_to_string')
def convert_date_to_string(date, format_date_type='dd MMMM yyyy'):
    return format_date(date, format_date_type, locale='id_ID') if date else ''


@register.filter(is_safe=True, name='get_pn_image_url')
def get_pn_image_url(item_id):
    if Image.objects.filter(
        image_source=item_id, image_type=ImageType.STREAMLINED_PN, image_status=Image.CURRENT
    ):
        image_obj = Image.objects.filter(
            image_source=item_id, image_type=ImageType.STREAMLINED_PN, image_status=Image.CURRENT
        ).last()
        return image_obj.public_image_url


@register.filter(is_safe=True, name='format_rupiahs_with_no_space')
def format_rupiahs_with_no_space(rupiahs, arg):
    if rupiahs:
        if arg == 'yes':
            return "Rp%s.00,-" % (format_decimal(rupiahs, locale='id_ID'))
        elif arg == 'no_currency':
            return "%s" % (format_decimal(rupiahs, locale='id_ID'))
        else:
            return "Rp%s" % (format_decimal(rupiahs, locale='id_ID'))
    else:
        if arg == "default-0":
            return "Rp0"
        return '-'


@register.filter(is_safe=True, name='total_page_count')
def total_page_count(data_count):
    import math
    fixed_page = 2
    page_max_data_from_sec_page = 24
    total_page  = 0
    first_page_data_count = 8
    if not data_count:
        total_page = 1
        return total_page + fixed_page

    if data_count > 0 and data_count <= first_page_data_count:
        total_page = 1
    elif data_count > first_page_data_count:
        data_count = data_count - first_page_data_count
        total_page = (math.ceil(data_count  / page_max_data_from_sec_page)) + 1

    return total_page + fixed_page


@register.filter(is_safe=True, name='flag_for_table_open')
def flag_for_table_open(data_count):
    page_max_data_from_sec_page = 24
    table_open_flag = False
    first_page_data_count = 8
    if data_count == 1:
        table_open_flag = True
    elif (data_count - (first_page_data_count + 1)) % page_max_data_from_sec_page == 0:
        table_open_flag = True

    return table_open_flag


@register.filter(is_safe=True, name='flag_for_table_close')
def flag_for_table_close(data_count):
    page_max_data_from_sec_page = 24
    table_close_flag = False
    first_page_data_count = 8
    if (data_count - first_page_data_count) % page_max_data_from_sec_page == 0:
        table_close_flag = True

    return table_close_flag

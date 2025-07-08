import re

from juloserver.julo.product_lines import ProductLineCodes


def mf_web_app_filter_search_field(keyword):
    from django.core.validators import ValidationError, validate_email
    from django.db.models import Max

    from juloserver.account.models import Account

    keyword = keyword.strip()
    if keyword[:1] == '+':
        keyword = keyword[1:]
    if keyword.isdigit():
        account_id_max = Account.objects.aggregate(Max('id'))['id__max']
        if len(keyword) == 2 and int(keyword) == ProductLineCodes.AXIATA_WEB:
            return 'product_line_id', [int(keyword)]
        elif len(keyword) == 10 and keyword[:1] == '2':
            return 'id', keyword
        elif int(keyword) in range(1, account_id_max + 1):
            return 'account_id', [int(keyword)]
        else:
            mobile_phone_regex = re.compile(r'^(^\+62\s?|^62\s?|^0)(\d{3,4}-?){2}\d{3,4}$')
            if mobile_phone_regex.match(keyword):
                return 'partnership_customer_data__phone_number', keyword
            else:
                return 'partnership_customer_data__nik', keyword
    else:
        try:
            validate_email(keyword)
            return 'partnership_customer_data__email', keyword
        except ValidationError:
            return 'fullname', keyword


def mf_web_app_loan_filter_search_field(keyword):
    from django.core.validators import ValidationError, validate_email
    from django.db.models import Max

    from juloserver.account.models import Account

    keyword = keyword.strip()
    if keyword[:1] == '+':
        keyword = keyword[1:]
    if keyword.isdigit():
        account_id_max = Account.objects.aggregate(Max('id'))['id__max']
        if len(keyword) == 2 and int(keyword) == ProductLineCodes.AXIATA_WEB:
            return 'product_line_id', [int(keyword)]
        elif len(keyword) == 10:
            if keyword[:1] == '3':
                return 'id', keyword
            elif keyword[:1] == '2':
                return 'account__partnership_customer_data__application__id'
        elif int(keyword) in range(1, account_id_max + 1):
            return 'account_id', [int(keyword)]
        else:
            mobile_phone_regex = re.compile(r'^(^\+62\s?|^62\s?|^0)(\d{3,4}-?){2}\d{3,4}$')
            if mobile_phone_regex.match(keyword):
                return 'account__partnership_customer_data__phone_number', keyword
            else:
                return 'account__partnership_customer_data__nik', keyword
    else:
        try:
            validate_email(keyword)
            return 'account__partnership_customer_data__email', keyword
        except ValidationError:
            return 'account__partnership_customer_data__application__fullname', keyword

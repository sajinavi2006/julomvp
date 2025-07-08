from builtins import range

from django.template import Library

register = Library()


def _normalize_search_params(search_params):
    if isinstance(search_params, str) or not isinstance(search_params, (list, tuple)):
        search_params = ({'name': 'q', 'value': search_params},)
    for i in range(len(search_params)):
        search_params[i].setdefault('verbose_name', search_params[i]['name'])
    return search_params


def _generate_get_request(search_params):
    search_params = _normalize_search_params(search_params)
    get_request = '&'.join(
        [
            '%(name)s=%(value)s' % p
            for p in search_params
            if p.get('name', '') and p.get('value', '')
        ]
    )
    return '&' + get_request if get_request else ''


@register.inclusion_tag('core/pagination1.html', takes_context=True)
def pagination(context, is_paginated, paginator, page_obj, path_info, search_params):
    get_request = _generate_get_request(search_params)
    return {
        'is_paginated': is_paginated,
        'paginator': paginator,
        'page_obj': page_obj,
        'path_info': path_info,
        'get_request': get_request,
        'STATIC_URL': context['STATIC_URL'],
    }


@register.inclusion_tag('core/search_form.html', takes_context=True)
def search_form(context, search_params):
    search_params = _normalize_search_params(search_params)
    return {
        'search_params': search_params,
        # 'q_value': context['q_value'],
        'STATIC_URL': context['STATIC_URL'],
    }


@register.inclusion_tag('core/search_form_tmp.html', takes_context=True)
def search_form_tmp(context, search_params, search_cert, msg_confirm=None):
    search_params = _normalize_search_params(search_params)
    if msg_confirm:
        return {
            'search_params': search_params,
            'search_cert': search_cert,
            'msg_confirm': msg_confirm,
        }
    else:
        return {'search_params': search_params, 'search_cert': search_cert}


@register.inclusion_tag('core/search_form_app.html', takes_context=True)
def search_form_app(
    context, form_get, obj, status_app, err_msg_here, extend_search_key='', partner=False
):
    if partner == 'partner':
        partner = True
    else:
        partner = False

    return {
        'form': form_get,
        'obj': obj,
        'status_app': status_app,
        'err_msg': err_msg_here,
        'search_key': extend_search_key,
        'partner': partner,
    }


@register.inclusion_tag('core/search_form_w_value.html', takes_context=True)
def search_form_w_value(context, search_params):
    search_params = _normalize_search_params(search_params)
    return {'search_params': search_params, 'STATIC_URL': context['STATIC_URL']}


@register.inclusion_tag('core/search_form_product.html', takes_context=True)
def search_form_product(context, form_get, obj, err_msg_here):
    return {'form': form_get, 'obj': obj, 'err_msg': err_msg_here}


@register.inclusion_tag('core/price_list_search.html', takes_context=True)
def price_list_search(context, form_get, obj):
    return {
        'form': form_get,
        'obj': obj,
    }


@register.inclusion_tag('core/tracking_delivery_search.html', takes_context=True)
def tracking_delivery_search(context, form_get, obj):
    return {
        'form': form_get,
        'obj': obj,
    }


@register.inclusion_tag('core/pagination2.html', takes_context=True)
def pagination2(context, is_paginated, paginator, page_obj, search_params, adjacent_pages=2):
    return pagination4(context, is_paginated, paginator, page_obj, search_params, adjacent_pages)


@register.inclusion_tag('core/pagination1.html', takes_context=True)
def pagination4(context, is_paginated, paginator, page_obj, search_params, adjacent_pages=2):
    """
    To be used in conjunction with the object_list generic view.

    Adds pagination context variables for use in displaying first, adjacent and
    last page links in addition to those created by the object_list generic
    view.

    Required context variables: paged: The Paginator.page() instance.

    used on template:
    {% pagination2 paginator page_obj q %}
    or
    {% pagination4 paginator page_obj q %}

    """
    # print dir(context)
    # print dir(page_obj)
    # print dir(page_obj.paginator)
    context_in = page_obj
    get_request = _generate_get_request(search_params)

    # print "context_in.page: " , context_in.number
    page_numbers = [
        n
        for n in range(page_obj.number - adjacent_pages, page_obj.number + adjacent_pages + 1)
        if n > 0 and n <= context_in.paginator.num_pages
    ]
    # print "page_numbers: ", page_numbers
    # print "context['results_per_page']: ", context['results_per_page']
    return {
        #         'hits': context_in['hits'],
        'results_per_page': context['results_per_page'],
        'page': page_obj.number,
        'pages': context_in.paginator.num_pages,
        'page_numbers': page_numbers,
        'next': context_in.next_page_number,
        'previous': context_in.previous_page_number,
        'has_next': context_in.has_next,
        'has_previous': context_in.has_previous,
        'show_first': 1 not in page_numbers,
        'show_last': context_in.paginator.num_pages not in page_numbers,
        'is_paginated': is_paginated,
        'paginator': paginator,
        'page_obj': page_obj,
        'get_request': get_request,
        'parameters': context['parameters'] if 'parameters' in context else '',
    }


@register.filter
def index(sequence, position):
    return sequence[position]


@register.filter
def key_value(product_dict, key):
    value = product_dict.get(key, '')
    return value


@register.filter
def waiver_bucket_name(bucket_name):
    bucket_name_mapping = {
        'bucket_0': 'Current / DPD Minus',
        'bucket_1': 'Bucket 1',
        'bucket_2': 'Bucket 2',
        'bucket_3': 'Bucket 3',
        'bucket_4': 'Bucket 4',
        'bucket_5': 'Bucket 5',
    }
    value = bucket_name_mapping[bucket_name]
    return value


@register.filter
def verbose_name(instance):
    return instance._meta.verbose_name


@register.inclusion_tag(
    'object/merchant_financing_web_app/core/mf_web_app_loan_list_search_form.html',
    takes_context=True,
)
def mf_web_app_loan_list_search_form(
    context, form_get, obj, status_app, err_msg_here, extend_search_key=''
):
    return {
        'form': form_get,
        'obj': obj,
        'status_app': status_app,
        'err_msg': err_msg_here,
        'search_key': extend_search_key,
    }

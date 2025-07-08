from django import template

from juloserver.julo_financing.constants import JFinancingStatus
from juloserver.julo_financing.models import JFinancingVerification

register = template.Library()


@register.inclusion_tag('j_financing_bucket_count.html', takes_context=True)
def julo_financing_bucket(context: dict) -> dict:
    bucket_count = JFinancingVerification.objects.exclude(
        validation_status=JFinancingStatus.INITIAL,
    ).count()

    return {
        'user': context['user'],
        'bucket_info': {'title': 'Smartphone Financing', 'count': bucket_count},
    }


@register.filter
def value_from_dict(dictionary: dict, key: str) -> str:
    return dictionary.get(key, '')

from django import template

from juloserver.balance_consolidation.models import BalanceConsolidationVerification

register = template.Library()


@register.inclusion_tag('bucket_count.html', takes_context=True)
def balance_consolidation_bucket(context):
    bucket_count = BalanceConsolidationVerification.objects.count()
    return {
        'user': context['user'],
        'bucket_info': {'title': 'Balance Cons', 'count': bucket_count},
    }

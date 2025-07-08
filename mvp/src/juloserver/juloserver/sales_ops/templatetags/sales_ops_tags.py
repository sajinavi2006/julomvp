from django import template

from juloserver.sales_ops.services import sales_ops_services

register = template.Library()


@register.inclusion_tag('sales_ops/bucket_count.html', takes_context=True)
def sales_ops_bucket(context):
    buckets_count = sales_ops_services.count_sales_ops_bucket_on_dashboard()
    return {
        'user': context['user'],
        'buckets_count': buckets_count
    }

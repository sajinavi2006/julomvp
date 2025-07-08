from django.conf.urls import url
from ..views import crm_views as views


urlpatterns = [
    url(
        r'^overpaid_detail/(?P<case_id>\d+)$',
        views.overpaid_detail,
        name='overpaid_detail',
    ),
]

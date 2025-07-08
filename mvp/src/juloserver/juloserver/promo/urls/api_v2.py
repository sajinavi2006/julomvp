from django.conf.urls import url
from rest_framework import routers

from juloserver.promo.views import LoanPromoCodeCheckV2, LoanPromoCodeListViewV2

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^promo-code/check/$', LoanPromoCodeCheckV2.as_view(), name='promo_code_check_v2'),
    url(
        r'^promo-codes/(?P<loan_xid>[0-9]+)/$',
        LoanPromoCodeListViewV2.as_view(),
        name='promo_code_list_v2'
    )
]

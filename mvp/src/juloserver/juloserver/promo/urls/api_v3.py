from django.conf.urls import url
from rest_framework import routers

from juloserver.promo.views_v3 import LoanPromoCodeCheckV3, LoanPromoCodeListViewV3

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^promo-code/check/$', LoanPromoCodeCheckV3.as_view(), name='promo_code_check_v3'),
    url(
        r'^promo-codes/$',
        LoanPromoCodeListViewV3.as_view(),
        name='promo_code_list_v3'
    )
]

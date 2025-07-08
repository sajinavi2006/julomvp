from django.conf.urls import url
from rest_framework import routers

from ..views import LoanPromoCodeCheckV1, PromoCMSList, PromoCMSDetail, PromoCodeTnCRetrieveView, \
    PromoCMSGetSearchCategories

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^promo-code/check/$', LoanPromoCodeCheckV1.as_view()),
    url(
        r'^promo-code/tnc/(?P<promo_code>[A-Za-z0-9]+)/$', PromoCodeTnCRetrieveView.as_view()
    ),
    url(r'^promo-code/cms/promo_list$', PromoCMSList.as_view()),
    url(r'^promo-code/cms/promo_detail$', PromoCMSDetail.as_view()),
    url(r'^promo-code/cms/get_search_categories/$', PromoCMSGetSearchCategories.as_view()),
]

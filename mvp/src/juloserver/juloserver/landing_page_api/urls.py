from rest_framework import routers

import juloserver.landing_page_api.views as views

router = routers.DefaultRouter()
router.register(r'^faq', views.FAQItemViewSet, base_name='faq')
router.register(r'^career', views.LandingPageCareerViewSet, base_name='career')
router.register(r'^section', views.LandingPageSectionViewSet, base_name='section')
router.register(
    r'^delete_account_request',
    views.DeleteAccountRequestViewSet,
    base_name='delete_account_request',
)
router.register(
    r'^consent-withdrawal/request',
    views.ConsentWithdrawalRequestView,
    base_name='consent-withdrawal-request',
)

urlpatterns = [
]

urlpatterns += router.urls

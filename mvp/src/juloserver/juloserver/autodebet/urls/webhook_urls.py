from django.conf.urls import url
from rest_framework import routers

from juloserver.autodebet.views import views_mandiri_api_v1 as views
from juloserver.autodebet.views import views_bni_api_v1 as views_bni
from juloserver.autodebet.views import views_dana_api_v1 as views_dana
from juloserver.autodebet.views import views_api_v1 as views_api_v1
router = routers.DefaultRouter()

urlpatterns = [
    url(r'^mandiri/v1/purchase_notification$', views.PurchaseNotificationView.as_view()),
    url(r'^mandiri/v1/binding_notification$', views.ActivationNotificationCallbackView.as_view()),
    url(r'^bni/v1/binding-notification$', views_bni.BNICardBindCallbackView.as_view()),
    url(r'^bni/v1/payment-notification$', views_bni.BNIPurchaseCallbackView.as_view()),
    url(r'^dana/v1/payment-notification$', views_dana.PaymentNotificationCallbackView.as_view()),
    url(r'^idfy/v1/video/callback$', views_api_v1.IdfyCallbackCompleted.as_view()),
    url(r'^idfy/v1/video/callback/session-drop-off', views_api_v1.IdfyCallbackDropOff.as_view()),
]

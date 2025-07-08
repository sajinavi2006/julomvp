from django.conf.urls import include, url
from rest_framework import routers

from juloserver.bpjs.views import view_v1 as view

router = routers.DefaultRouter()

urlpatterns = [
    url(r"^", include(router.urls)),
    url(
        r"^login/(?P<app_type>.*)/(?P<customer_id>.*)/(?P<application_id>.*)/$",
        view.LoginUrlView.as_view(),
    ),
    url(r"^callback/tongdun/task", view.TongdunTaskCallbackView.as_view()),
    url(r"^bpjs_pdf/(?P<application_id>.*)/$", view.bpjs_pdf_view, name="bpjs_pdf"),
]

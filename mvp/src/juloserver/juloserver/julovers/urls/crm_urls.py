from django.conf.urls import url

from juloserver.julovers.views import crm_views

urlpatterns = [
    url(r'^upload_julovers_data$', crm_views.UploadJuloversData, name='upload_julovers_data'),
    url(r'^upload_history$', crm_views.UploadHistory.as_view(), name='upload_history'),
]

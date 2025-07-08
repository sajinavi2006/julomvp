from django.conf.urls import url
from rest_framework import routers
from juloserver.employee_financing import views


router = routers.DefaultRouter()

urlpatterns = [
    url(r'^auth$', views.EmployeeFinancingAuth.as_view()),
    url(r'^submit-application$', views.SubmitWFApplicationEmployeeFinancing.as_view()),
    url(r'^submit-disbursement$', views.SubmitWFDisbursementEmployeeFinancingView.as_view()),
    url(r'^view-image', views.ShowImage.as_view()),
    url(r'^validate$', views.ValidateDOBEmployeeFinancingView.as_view()),
]

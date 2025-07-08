from django.conf.urls import include, url
from rest_framework import routers

from juloserver.registration_flow import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    # Check phone number existance
    url(r'^check', views.CheckPhoneNumberOld.as_view()),
    # validate nik/email
    url(r'^validate', views.ValidateNikEmail.as_view()),
    # Generate Customer Registration Flow
    url(r'^generate-customer', views.GenerateCustomer.as_view()),
    url(r'^register', views.RegisterPhoneNumber.as_view()),
    url(r'^prepopulate-form', views.PrepopulateForm.as_view()),
    url(r'^pre-register-check$', views.PreRegister.as_view()),
    url(r'^sync-registration', views.SyncRegisterUser.as_view()),
]

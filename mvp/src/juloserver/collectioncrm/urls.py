from django.conf.urls import include, url
from rest_framework import routers

from . import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),

    # Endpoint for getting all history in application page
    url(r'^agents/(?P<pk>[0-9]+)/$', views.AgentViewSet.as_view({'delete': 'destroy', 'put': 'update'})),
    url(r'^agents/$',views.AgentViewSet.as_view({'get': 'list','post':'post'})),
    url(r'^agents/roles$',views.GroupViewSet.as_view({'get': 'list'})),
    url(r'^crm/buckets$', views.BucketViewSet.as_view({'get': 'list'})),
    url(r'^crm/customers/emails$', views.EmailViewSet.as_view({'get': 'list'})),
    url(r'^crm/customers$', views.CustomerViewSet.as_view({'get': 'list'})),

    url(r'^crm/performance$', views.PerformanceViewSet.as_view()),
   
]

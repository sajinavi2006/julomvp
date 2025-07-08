from builtins import object
from factory.django import DjangoModelFactory
from juloserver.application_form.models import CompanyLookup


class CompanyLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = CompanyLookup

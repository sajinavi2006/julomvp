from factory import SubFactory
from factory.django import DjangoModelFactory
from juloserver.julo.tests.factories import CustomerFactory
from juloserver.rating.models import InAppRating


class RatingFactory(DjangoModelFactory):
    class Meta(object):
        model = InAppRating

    customer = SubFactory(CustomerFactory)
    rating = 5
    description = 'Sudah mantap aplikasinya'
    csat_score = 5
    csat_description = 'Sudah mantap aplikasinya'
    source = 1

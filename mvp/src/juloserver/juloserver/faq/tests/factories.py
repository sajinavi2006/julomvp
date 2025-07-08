from factory.django import DjangoModelFactory

from juloserver.faq.models import (
    Faq,
)


class FaqFactory(DjangoModelFactory):
    class Meta:
        model = Faq

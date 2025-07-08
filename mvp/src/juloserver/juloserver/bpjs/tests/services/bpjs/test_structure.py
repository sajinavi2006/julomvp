from unittest import TestCase

import pytest

from juloserver.bpjs.services import Bpjs
from juloserver.julo.tests.factories import ApplicationFactory


@pytest.mark.django_db
class TestStructure(TestCase):
    def setUp(self) -> None:
        self.application = ApplicationFactory()

    def test_set_application_in_property(self):
        bpjs = Bpjs()
        bpjs.application = self.application
        self.assertEqual(bpjs.application.id, self.application.id)

    def test_set_application_in_argument(self):
        bpjs = Bpjs(self.application)
        self.assertEqual(bpjs.application.id, self.application.id)

    def test_set_application_in_keyword_argument(self):
        bpjs = Bpjs(application=self.application)
        self.assertEqual(bpjs.application.id, self.application.id)

    def test_set_application_in_chained_method(self):
        bpjs = Bpjs().with_application(self.application)
        self.assertEqual(bpjs.application.id, self.application.id)

    def test_set_provider_in_property(self):
        bpjs = Bpjs()
        bpjs.provider = "brick"
        self.assertEqual(bpjs.provider, "brick")

    def test_set_provider_in_argument(self):
        bpjs = Bpjs(self.application, "brick")
        self.assertEqual(bpjs.provider, "brick")

    def test_set_provider_in_keyword_argument(self):
        bpjs = Bpjs(provider="brick")
        self.assertEqual(bpjs.provider, "brick")

    def test_set_provider_in_chained_method(self):
        bpjs = Bpjs().using_provider("brick")
        self.assertEqual(bpjs.provider, "brick")

    def test_set_provider_not_allowed(self):
        with pytest.raises(LookupError) as exception:
            Bpjs(provider="the-riddle")

        self.assertEqual(str(exception.value), "Bpjs provider not found.")

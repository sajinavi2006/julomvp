from django.test import TestCase
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
)
from juloserver.pin.utils import get_first_name


class TestGetFirstName(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)

    def test_get_first_name_from_customer_and_no_application(self):
        self.customer.fullname = 'Harry Potter'
        self.customer.save()

        first_name = get_first_name(self.customer)
        self.assertEquals(first_name, 'Harry')

    def test_get_first_name_if_its_no_application(self):
        self.customer.fullname = None
        self.customer.save()

        first_name = get_first_name(self.customer)
        self.assertEquals(first_name, 'Pelanggan setia JULO')

    def test_get_first_name_raise_index_error(self):
        self.customer.fullname = ''
        self.customer.save()

        first_name = get_first_name(self.customer)
        self.assertRaises(IndexError)
        self.assertEquals(first_name, 'Pelanggan setia JULO')

    def test_get_first_name_from_customer(self):
        self.application = ApplicationFactory(customer=self.customer, fullname=None)
        self.customer.fullname = 'Harry Potter'
        self.customer.save()

        first_name = get_first_name(self.customer)
        self.assertEquals(first_name, 'Harry')

    def test_get_first_name_from_application(self):
        self.application = ApplicationFactory(
            customer=self.customer,
            fullname='Harry Potter',
        )
        self.customer.fullname = None
        self.customer.save()

        first_name = get_first_name(self.customer)
        self.assertEquals(first_name, 'Harry')

    def test_get_first_name_if_its_None(self):
        self.application = ApplicationFactory(
            customer=self.customer,
            fullname=None,
        )
        self.customer.fullname = None
        self.customer.save()

        first_name = get_first_name(self.customer)
        self.assertEquals(first_name, 'Pelanggan setia JULO')

    def test_get_first_name_from_application_raise_index_error(self):
        self.application = ApplicationFactory(
            customer=self.customer,
            fullname='',
        )
        self.customer.fullname = None
        self.customer.save()

        first_name = get_first_name(self.customer)
        self.assertRaises(IndexError)
        self.assertEquals(first_name, 'Pelanggan setia JULO')

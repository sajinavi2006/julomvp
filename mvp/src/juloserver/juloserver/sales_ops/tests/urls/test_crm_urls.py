from unittest import TestCase

from django.core.urlresolvers import reverse


class TestCRMUrl(TestCase):
    def test_list(self):
        url = reverse('sales_ops.crm:list')
        self.assertEqual(url, '/sales-ops/list')

    def test_detail(self):
        url = reverse('sales_ops.crm:detail', args=[123])
        self.assertEqual(url, '/sales-ops/detail/123')

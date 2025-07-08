from unittest import TestCase

from django.core.urlresolvers import reverse

from juloserver.portal.object.dashboard import functions
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.sales_ops.constants import SalesOpsRoles


class TestSetRolesUrl(TestCase):
    def test_for_collection_bucket_roles(self):
        check_roles = (
            JuloUserRoles.COLLECTION_SUPERVISOR,
            JuloUserRoles.COLLECTION_BUCKET_1,
            JuloUserRoles.COLLECTION_BUCKET_2,
            JuloUserRoles.COLLECTION_BUCKET_3,
            JuloUserRoles.COLLECTION_BUCKET_4,
            JuloUserRoles.COLLECTION_BUCKET_5,
        )
        for role in check_roles:
            value = functions.set_roles_url(role)
            self.assertEqual(reverse('dashboard:all_collection_dashboard', args=[role]), value)

    def test_for_sales_ops(self):
        value = functions.set_roles_url(SalesOpsRoles.SALES_OPS)
        self.assertEqual(value, reverse('sales_ops.crm:list'))

    def test_for_unknown_role(self):
        value = functions.set_roles_url('unknown_role')
        self.assertIsNone(value)

import datetime
from time import timezone
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone

from juloserver.cfs.tests.factories import AgentFactory
from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.sales_ops.forms import (
    SalesOpsCRMLineupDetailForm,
    SalesOpsCRMLineupListFilterForm,
)
from juloserver.sales_ops.tests.factories import (
    SalesOpsLineupFactory,
    SalesOpsAgentAssignmentFactory,
)


class TestSalesOpsCRMLineupDetailForm(TestCase):
    def setUp(self):
        self.datetime = timezone.localtime(datetime.datetime(2020, 1, 1, 10, 12, 0))
        self.lineup = SalesOpsLineupFactory(inactive_until=self.datetime, reason='test reason')

    def test_fill_form(self):
        form = SalesOpsCRMLineupDetailForm()
        form.fill_form(self.lineup)

        self.assertEqual('2020-01-01 10:12', form.fields['inactive_until'].initial)
        self.assertEqual('test reason', form.fields['inactive_note'].initial)

    def test_save_empty(self):
        data = {
            'inactive_until': '',
            'inactive_note': ''
        }
        form = SalesOpsCRMLineupDetailForm(data=data)
        self.assertTrue(form.is_valid())

        form.save(self.lineup)

        self.lineup.refresh_from_db()
        self.assertIsNone(self.lineup.inactive_until)
        self.assertEqual('', self.lineup.reason)

    def test_save_no_data(self):
        data = {}
        form = SalesOpsCRMLineupDetailForm(data=data)
        self.assertTrue(form.is_valid())

        form.save(self.lineup)

        localtime = timezone.localtime(datetime.datetime(2020, 1, 1, 10, 12, 0))
        self.lineup.refresh_from_db()
        self.assertEqual(localtime, self.lineup.inactive_until)
        self.assertEqual('test reason', self.lineup.reason)

    def test_save_with_data(self):
        data = {
            'inactive_until': '2021-01-31 10:12',
            'inactive_note': 'test reason edited'
        }
        form = SalesOpsCRMLineupDetailForm(data=data)
        self.assertTrue(form.is_valid())

        form.save(self.lineup)
        localtime = timezone.localtime(datetime.datetime(2021, 1, 31, 10, 12, 0))
        self.lineup.refresh_from_db()
        self.assertEqual(localtime, self.lineup.inactive_until)
        self.assertEqual('test reason edited', self.lineup.reason)


class TestSalesOpsCRMLineupListFilterForm(TestCase):
    def test_validate_filter_agent(self):
        group = Group(name="sales_ops")
        group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(group)
        agent = AgentFactory(user=self.user)
        SalesOpsAgentAssignmentFactory(agent_id=agent.id, completed_date=timezone.now())
        data = {
            'filter_agent': agent.id
        }

        form = SalesOpsCRMLineupListFilterForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_validate_filter_agent_false(self):
        agent = AgentFactory()
        SalesOpsAgentAssignmentFactory(agent_id=agent.id, completed_date=None)
        data = {
            'filter_agent': agent.id
        }

        form = SalesOpsCRMLineupListFilterForm(data=data)
        self.assertFalse(form.is_valid(), form.errors)

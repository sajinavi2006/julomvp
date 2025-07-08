from unittest import mock
from factory import Iterator

from django.core.urlresolvers import reverse
from django.test import TestCase

from juloserver.julo.constants import SkiptraceResultChoiceConst
from juloserver.julo.models import SkiptraceResultChoice
from juloserver.apiv2.tests.factories import EtlJobFactory
from juloserver.julo.tests.factories import (
    ApplicationHistoryFactory,
    ApplicationJ1Factory,
    ApplicationNoteFactory,
    AuthUserFactory,
    DeviceScrapedDataFactory,
    CustomerFactory,
    SecurityNoteFactory,
    SkiptraceFactory,
    SkiptraceResultChoiceFactory,
)
from juloserver.new_crm.services import application_services


class TestGetApplicationScrapeData(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()

    def test_no_data(self):
        ret_val = application_services.get_application_scrape_data(self.application)
        self.assertEqual([], ret_val)

    @mock.patch('juloserver.new_crm.services.application_services.Bpjs')
    def test_bpjs_data(self, mock_bpjs_init):
        mock_bpjs = mock.MagicMock()
        mock_bpjs.is_scraped.return_value = True
        mock_bpjs_init.return_value = mock_bpjs

        ret_val = application_services.get_application_scrape_data(self.application)

        expected_bpjs_data = {
            "type": "bpjs",
            "filename": "BPJS_Report_{}.pdf".format(self.application.id),
            "url": reverse("bpjs:bpjs_pdf", args=[self.application.id]),
            "is_downloadable": True,
            "is_sheet": False,
            "is_viewable": False
        }
        self.assertEqual([expected_bpjs_data], ret_val)

    @mock.patch('juloserver.julo.models.get_s3_url')
    def test_sd_data(self, mock_get_s3_url):
        mock_get_s3_url.return_value = 'https://s3.url/path/to/file.xlsx'
        DeviceScrapedDataFactory(
            application_id=self.application.id,
            url='path/to/file.xlsx',
            reports_url='path/to/file.xlsx',
            service='s3',
        )

        ret_val = application_services.get_application_scrape_data(self.application)

        expected_sd_data = {
            "type": "sd",
            "filename": "file.xlsx",
            "url": 'https://s3.url/path/to/file.xlsx',
            "is_downloadable": False,
            "is_sheet": True,
            "is_viewable": True
        }
        self.assertEqual([expected_sd_data], ret_val)

    @mock.patch('juloserver.apiv2.models.get_s3_url')
    def test_bank_data(self, mock_get_s3_url):
        mock_get_s3_url.return_value = 'https://s3.url/path/to/file.xlsx'
        EtlJobFactory(
            application_id=self.application.id,
            status='load_success',
            data_type='bca',
            s3_url_bank_report='path/to/file.xlsx',
        )
        ret_val = application_services.get_application_scrape_data(self.application)

        expected_bank_data = {
            "type": "bank",
            "filename": "file.xlsx",
            "url": 'https://s3.url/path/to/file.xlsx',
            "is_downloadable": True,
            "is_sheet": True,
            "is_viewable": True
        }
        self.assertEqual([expected_bank_data], ret_val)

class TestGetApplicationSkiptraceList(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationJ1Factory(customer=self.customer)

    def test_get_application_skiptrace_list(self):
        SkiptraceFactory.create_batch(3, customer=self.customer)

        ret_val = application_services.get_application_skiptrace_list(self.application)
        self.assertEqual(3, len(ret_val))


class TestGetApplicationSkiptraceResultList(TestCase):
    def test_get_application_skiptrace_result_list(self):
        result_names = SkiptraceResultChoiceConst.basic_skiptrace_result_list()
        SkiptraceResultChoiceFactory.create_batch(len(result_names), name=Iterator(result_names))

        SkiptraceResultChoiceFactory(name='random name')

        ret_val = application_services.get_application_skiptrace_result_list()

        self.assertEqual(len(result_names), len(ret_val))


class TestGetApplicationStatusHistories(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()
        self.user = AuthUserFactory(username='testuser')

    def test_get_application_status_histories(self):
        ApplicationHistoryFactory(application_id=self.application.pk, changed_by=self.user)
        ApplicationNoteFactory(application_id=self.application.pk, added_by=self.user.id)
        SecurityNoteFactory(customer=self.application.customer, added_by=self.user)

        ret_val = application_services.get_application_status_histories(self.application)

        self.assertEqual(3, len(ret_val))

    def test_security_note_data(self):
        security_note = SecurityNoteFactory(
            customer=self.application.customer,
            added_by=self.user,
            note_text="test note"
        )

        ret_val = application_services.get_application_status_histories(self.application)
        expected_data = {
            'id': str(security_note.id),
            'note_text': 'test note',
            'type': 'Security Change',
            'agent': 'testuser',
            'updated_at': str(security_note.cdate),
        }
        self.assertEqual(1, len(ret_val))
        self.assertEqual(expected_data, dict(ret_val[0]))

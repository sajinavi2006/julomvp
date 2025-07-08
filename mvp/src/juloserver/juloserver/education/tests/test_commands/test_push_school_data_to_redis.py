import json
from io import StringIO
from unittest.mock import patch
from django.test import TestCase
from django.core.management import call_command
from fakeredis import FakeServer, FakeStrictRedis

from juloserver.education.tests.factories import SchoolFactory


class PushSchoolDataToRedisTestCase(TestCase):
    def setUp(self):
        self.school1 = SchoolFactory(id=1, name='School1', city='City1')
        self.school1.save()
        self.school2 = SchoolFactory(id=2, name='School2', city='City2')
        self.school2.save()
        self.school3 = SchoolFactory(id=3, name='School3', city='City3')
        self.school3.save()

    def _get_and_compare_school_data(self, fake_redis_client, school):
        school_data = json.loads(
            fake_redis_client.hget(name='school_ac:d', key='{}\x01'.format(school.id)).decode()
        )
        self.assertEqual(school_data['id'], school.id)
        self.assertEqual(school_data['name'], school.name)
        self.assertEqual(school_data['city'], school.city)

    @patch('juloserver.julocore.redis_completion_py3.RedisEnginePy3.get_client')
    def test_push_school_data_to_redis(self, mock_get_client):
        fake_redis_client = FakeStrictRedis(server=FakeServer())
        mock_get_client.return_value = fake_redis_client

        # Only push school id >= 2
        out = StringIO()
        call_command('push_school_data_to_redis', '--start_id', '2', stdout=out)
        self.assertIn('SUCCESS! Pushed 2 schools', str(out.getvalue()))
        self.assertEqual(len(fake_redis_client.hvals('school_ac:d')), 2)
        self._get_and_compare_school_data(fake_redis_client=fake_redis_client, school=self.school2)
        self._get_and_compare_school_data(fake_redis_client=fake_redis_client, school=self.school3)

        # Only push school 2 > id >= 0 and keep old data
        out = StringIO()
        call_command('push_school_data_to_redis', '--keep_old_data', '--end_id', '2', stdout=out)
        self.assertIn('SUCCESS! Pushed 1 schools', str(out.getvalue()))
        self.assertEqual(len(fake_redis_client.hvals('school_ac:d')), 3)
        self._get_and_compare_school_data(fake_redis_client=fake_redis_client, school=self.school1)

        # Fail by exist data before
        out = StringIO()
        with self.assertRaises(Exception):
            call_command('push_school_data_to_redis', '--keep_old_data', stdout=out)

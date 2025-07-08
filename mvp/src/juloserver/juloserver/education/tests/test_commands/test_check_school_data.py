import json
from io import StringIO
from unittest.mock import patch
from django.test import TestCase
from django.core.management import call_command
from fakeredis import FakeServer, FakeStrictRedis

from juloserver.education.tests.factories import SchoolFactory


class CheckSchoolDataTestCase(TestCase):
    def setUp(self):
        self.school1 = SchoolFactory(id=1, name='School1', city='City1')
        self.school1.save()
        self.school2 = SchoolFactory(id=2, name='School2', city='City2')
        self.school2.save()
        self.school3 = SchoolFactory(id=3, name='School3', city='City3')
        self.school3.save()

    @staticmethod
    def _add_school_data_to_redis(fake_redis_client, school):
        fake_redis_client.hset(
            'school_ac:d',
            '{}\x01'.format(school.id),
            json.dumps(
                {
                    'id': school.id,
                    'name': school.name,
                    'city': school.city,
                }
            ),
        )

    @patch('juloserver.julocore.redis_completion_py3.RedisEnginePy3.get_client')
    def test_check_school_data(self, mock_get_client):
        fake_redis_client = FakeStrictRedis(server=FakeServer())
        mock_get_client.return_value = fake_redis_client
        self._add_school_data_to_redis(fake_redis_client=fake_redis_client, school=self.school2)

        # Fail because DB has 3 records, but Redis have only 1
        out = StringIO()
        call_command('check_school_data', stdout=out)
        self.assertIn('ERROR! Length of school in DB is not equal in Redis', out.getvalue())

        # Success because only check 2 <= id < 3
        out = StringIO()
        call_command('check_school_data', '--start_id', '2', '--end_id', '3', stdout=out)
        self.assertIn('SUCCESS! 1 schools are identical between DB and Redis', out.getvalue())

        # Success
        self._add_school_data_to_redis(fake_redis_client=fake_redis_client, school=self.school1)
        self._add_school_data_to_redis(fake_redis_client=fake_redis_client, school=self.school3)
        out = StringIO()
        call_command('check_school_data', stdout=out)
        self.assertIn('SUCCESS! 3 schools are identical between DB and Redis', out.getvalue())

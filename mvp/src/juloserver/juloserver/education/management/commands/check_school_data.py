import json
import time

from django.core.management.base import BaseCommand
from juloserver.education.constants import REDIS_SCHOOL_AUTO_COMPLETE_HASH_TABLE_NAME
from juloserver.education.models import School
from juloserver.julocore.redis_completion_py3 import RedisEnginePy3


class Command(BaseCommand):
    help = 'Checks if all school data is in Redis'

    def add_arguments(self, parser):
        parser.add_argument(
            '--start_id', type=int, default=0, help='Filter ID by greater of equal than start_id'
        )
        parser.add_argument(
            '--end_id', type=int, default=None, help='Filter ID by less than end_id'
        )

    def handle(self, *args, **options):
        redis_completion_engine = RedisEnginePy3(prefix=REDIS_SCHOOL_AUTO_COMPLETE_HASH_TABLE_NAME)

        start_time = time.time()

        schools = School.objects.filter(
            is_active=True, is_verified=True, id__gte=options['start_id']
        )
        if options['end_id']:
            schools = schools.filter(id__lt=options['end_id'])

        total_school = schools.count()
        if total_school != redis_completion_engine.client.hlen(redis_completion_engine.data_key):
            self.stdout.write(
                self.style.ERROR('ERROR! Length of school in DB is not equal in Redis')
            )
            return False

        total_checked_school = 0

        for school in schools.iterator():
            try:
                redis_school_data = redis_completion_engine.client.hget(
                    name=redis_completion_engine.data_key,
                    key=redis_completion_engine.kcombine(school.id, ''),
                )
                redis_school = json.loads(redis_school_data.decode('utf-8'))
            except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
                self.stdout.write(
                    self.style.ERROR(
                        'ERROR! Data for id={} in Redis is wrong type'.format(school.id)
                    )
                )
                return False

            if (
                redis_school['id'] != school.id
                or redis_school['name'] != school.name
                or redis_school['city'] != school.city
            ):
                self.stdout.write(
                    self.style.ERROR(
                        'ERROR! Data for id={} in Redis is different from DB'.format(school.id)
                    )
                )
                return False

            total_checked_school += 1
            self.stdout.write(
                '[{}/{}] id={}, name={}'.format(
                    total_checked_school, total_school, school.id, school.name
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                'SUCCESS! {} schools are identical between DB and Redis'.format(total_school)
            )
        )
        self.stdout.write(
            self.style.SUCCESS('Total execution time: {} seconds '.format(time.time() - start_time))
        )

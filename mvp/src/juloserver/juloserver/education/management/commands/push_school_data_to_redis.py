import time

from django.core.management.base import BaseCommand

from juloserver.education.constants import REDIS_SCHOOL_AUTO_COMPLETE_HASH_TABLE_NAME
from juloserver.education.models import School
from juloserver.julocore.redis_completion_py3 import RedisEnginePy3


class Command(BaseCommand):
    help = 'Pushes all school data to Redis for autocomplete feature'

    def add_arguments(self, parser):
        parser.add_argument(
            '--keep_old_data', action='store_true', help='Flush old autocomplete data'
        )
        parser.add_argument(
            '--start_id', type=int, default=0, help='Filter ID by greater of equal than start_id'
        )
        parser.add_argument(
            '--end_id', type=int, default=None, help='Filter ID by less than end_id'
        )

    def handle(self, *args, **options):
        redis_completion_engine = RedisEnginePy3(prefix=REDIS_SCHOOL_AUTO_COMPLETE_HASH_TABLE_NAME)

        start_time = time.time()

        if not options['keep_old_data']:
            redis_completion_engine.flush()

        schools = School.objects.filter(
            is_active=True, is_verified=True, id__gte=options['start_id']
        )
        if options['end_id']:
            schools = schools.filter(id__lt=options['end_id'])

        total_school = schools.count()

        total_pushed_school = 0

        for school in schools.iterator():
            redis_completion_engine.store_json(
                obj_id=school.id,
                title=school.name,
                data_dict={
                    'id': school.id,
                    'name': school.name,
                    'city': school.city,
                },
            )
            total_pushed_school += 1
            self.stdout.write(
                self.style.SUCCESS(
                    '[{}/{}] id={}, name={}'.format(
                        total_pushed_school, total_school, school.id, school.name
                    )
                )
            )

        if redis_completion_engine.client.hlen(redis_completion_engine.data_key) >= total_school:
            self.stdout.write(self.style.SUCCESS('Soft checking is ok!'))
            self.stdout.write(self.style.SUCCESS('SUCCESS! Pushed {} schools'.format(total_school)))
        else:
            self.stdout.write(
                self.style.ERROR(
                    'Soft checking is error! '
                    'Length of hash table in redis is LESS than total school'
                )
            )
            self.stdout.write(self.style.ERROR('ERROR! Please try again'))

        self.stdout.write(
            self.style.SUCCESS('Total execution time: {} seconds'.format(time.time() - start_time))
        )

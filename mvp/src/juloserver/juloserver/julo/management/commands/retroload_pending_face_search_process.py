from builtins import str

from django.core.management.base import BaseCommand
from juloserver.face_recognition.models import FaceSearchProcess, FaceImageResult
from juloserver.face_recognition.services import CheckFaceSimilarity


class Command(BaseCommand):
    help = 'blast email for market survei'

    def add_arguments(self, parser):
        parser.add_argument(
            '--start-time',
            type=str,
            help='start timestamp for query'
        )

        parser.add_argument(
            '--end-time',
            type=str,
            help='end timestamp for query'
        )

        parser.add_argument(
            '--ids',
            type=int,
            nargs='+',
            help='list of ids intead of time range'
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS("=====================Start!====================="))
        ids = options.get('ids')
        if not ids:
            start_date = options.get('start_time')
            end_date = options.get('end_time')
            face_search_process_records = FaceSearchProcess.objects.select_related(
                'application'
            ).filter(
                cdate__gt=start_date, cdate__lt=end_date,
                status='pending')
        else:
            face_search_process_records = FaceSearchProcess.objects.select_related(
                'application').filter(id__in=ids)

        for face_search_process in face_search_process_records:
            self.stdout.write(
                self.style.SUCCESS('process_id, id={}'.format(face_search_process.id)))
            try:
                face_similarity_service = CheckFaceSimilarity(face_search_process.application)
                face_similarity_service.face_search_process = face_search_process
                face_image_result = FaceImageResult.objects.filter(
                    application=face_search_process.application).last()
                face_similarity_service.face_image_result = face_image_result
                face_similarity_service.face_search()
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR("Process face_search_process={} failed|error={}".format(
                        face_search_process.id, str(e))))
        self.stdout.write(
            self.style.SUCCESS("=====================Finished!====================="))

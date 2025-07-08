from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand

from juloserver.face_recognition.models import FaceRecommenderResult


class Command(BaseCommand):
    def handle(self, *args, **options):
        self.stdout.write(
            '======================================UPDATE RECOMMENDER DATA'
            '========================================'
        )

        face_recommender_results = FaceRecommenderResult.objects.all()

        for face_recommender_result in face_recommender_results:
            self.stdout.write('original date:' + str(face_recommender_result.apply_date))
            face_recommender_result.update_safely(
                apply_date=face_recommender_result.apply_date + relativedelta(months=1)
            )
            self.stdout.write('updated date:' + str(face_recommender_result.apply_date))

        self.stdout.write(
            '======================================FINISH UPDATE RECOMMENDER DATA'
            '========================================'
        )

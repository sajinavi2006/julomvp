from django.core.management.base import BaseCommand
from django.db.models import Q

from juloserver.face_recognition.models import FaceRecommenderResult, FaceSearchResult
from juloserver.julo.models import Image


class Command(BaseCommand):
    def handle(self, *args, **options):
        self.stdout.write(
            '======================================UPDATE RECOMMENDER DATA'
            '========================================'
        )

        face_recommender_results = FaceRecommenderResult.objects.all()

        for face_recommender_result in face_recommender_results:
            self.stdout.write(
                'original `face_recommender_result` id '
                + str(face_recommender_result.id)
                + ' :'
                + str(face_recommender_result.face_search_result)
            )

            image = Image.objects.filter(
                Q(image_type='selfie', image_source=face_recommender_result.match_application_id)
                | Q(
                    image_type='crop_selfie',
                    image_source=face_recommender_result.match_application_id,
                )
            ).all()

            for img in image:
                face_search_res = FaceSearchResult.objects.filter(
                    matched_face_image_id=img.id
                ).last()
                if face_search_res:
                    face_recommender_result.update_safely(face_search_result=face_search_res)
                    self.stdout.write(
                        'updated `face_recommender_result` id '
                        + str(face_recommender_result.id)
                        + ' :'
                        + str(face_search_res.id)
                    )

        self.stdout.write(
            '======================================FINISH UPDATE RECOMMENDER DATA'
            '========================================'
        )

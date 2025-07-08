from django.db import transaction
from juloserver.face_recognition.services import CheckFaceSimilarity
from juloserver.julo.models import Application
from juloserver.face_recognition.models import FaceSearchProcess


def trigger_check_face_similarity(app_id):
    # this code used for application that stuck pending on similar face checking
    app = Application.objects.get(pk=app_id)

    with transaction.atomic():
        try:
            check_face_similarity = CheckFaceSimilarity(app)
            check_face_similarity.check_face_similarity()
            check_face_similarity.face_search()
        except Exception as e:
            return str(e)


def check_trigger_check_face_similarity(app_id):
    app = Application.objects.get(pk=app_id)
    face_search_process = FaceSearchProcess.objects.filter(application=app).last()
    if face_search_process.status == 'pending':
        return "still pending"
    elif face_search_process.status == 'not_found':
        return "correct ! status 'not_found' should be correct"
    elif face_search_process.status == 'found':
        return "correct ! status 'found' should be correct"

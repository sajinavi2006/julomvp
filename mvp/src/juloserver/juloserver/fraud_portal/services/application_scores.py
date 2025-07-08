from juloserver.ana_api.models import PdCreditEarlyModelResult
from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.apiv2.models import PdCreditModelResult
from juloserver.application_flow.models import ShopeeScoring, MycroftResult
from juloserver.face_recognition.models import FaceSearchProcess, FaceSearchResult
from juloserver.julo.models import CreditScore, Application
from juloserver.liveness_detection.models import ActiveLivenessDetection, PassiveLivenessDetection
from juloserver.pii_vault.constants import PiiSource


def get_application_scores(application_ids: list) -> list:
    shopee_scores = {
        str(score.application_id): score.is_passed
        for score in get_shopee_scores_by_applications(application_ids)
    }
    mycroft_scores = {
        str(score.application_id): score.score
        for score in get_mycroft_scores_by_applications(application_ids)
    }
    credit_scores = {
        str(score.application_id): score.score
        for score in get_credit_scores_by_applications(application_ids)
    }
    active_liveness_scores = {
        str(score.application_id): score.score
        for score in get_active_liveness_scores_by_applications(application_ids)
    }
    passive_liveness_detection_scores = {
        str(score.application_id): score.score
        for score in get_passive_liveness_detection_by_applications(application_ids)
    }
    heimdall_scores = {
        str(score.application_id): score.pgood
        for score in get_heimdall_scores_by_applications(application_ids)
    }
    orion_scores = {
        str(score.application_id): score.pgood
        for score in get_orion_score_by_applications(application_ids)
    }

    application_scores = []

    for application_id in application_ids:
        application = Application.objects.get(id=application_id)
        if application:
            detokenized_application = detokenize_pii_antifraud_data(
                PiiSource.APPLICATION, [application], ['fullname']
            )[0]
            application_score = {
                'application_id': application.id,
                "application_full_name": detokenized_application.fullname,
                "shopee_score": shopee_scores.get(application_id),
                "application_similarity_score": get_application_similarity_score(application_id),
                "mycroft_score": mycroft_scores.get(application_id),
                "credit_score": credit_scores.get(application_id),
                "active_liveness_score": active_liveness_scores.get(application_id),
                "passive_liveness_score": passive_liveness_detection_scores.get(application_id),
                "heimdall_score": heimdall_scores.get(application_id),
                "orion_score": orion_scores.get(application_id),
            }
            application_scores.append(application_score)

    return application_scores


def get_application_similarity_score(application_id: int) -> float:
    application_similarity_score = None
    face_search_process = FaceSearchProcess.objects.filter(application_id=application_id).last()
    if face_search_process:
        face_search_result = FaceSearchResult.objects.filter(
            face_search_process_id=face_search_process.id
        ).last()
        application_similarity_score = getattr(face_search_result, 'similarity', None)

    return application_similarity_score


def get_shopee_scores_by_applications(application_ids: list) -> list:
    return ShopeeScoring.objects.filter(application_id__in=application_ids)


def get_mycroft_scores_by_applications(application_ids: list) -> list:
    return MycroftResult.objects.filter(application_id__in=application_ids)


def get_credit_scores_by_applications(application_ids: list) -> list:
    return CreditScore.objects.filter(application_id__in=application_ids)


def get_active_liveness_scores_by_applications(application_ids: list) -> list:
    return ActiveLivenessDetection.objects.filter(application_id__in=application_ids)


def get_passive_liveness_detection_by_applications(application_ids: list) -> list:
    return PassiveLivenessDetection.objects.filter(application_id__in=application_ids)


def get_heimdall_scores_by_applications(application_ids: list) -> list:
    return PdCreditModelResult.objects.filter(application_id__in=application_ids)


def get_orion_score_by_applications(application_ids: list) -> list:
    return PdCreditEarlyModelResult.objects.filter(application_id__in=application_ids)

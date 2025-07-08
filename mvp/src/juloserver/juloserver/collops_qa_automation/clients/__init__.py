from django.conf import settings


def get_julo_qa_airudder():
    from .quality_assurance_airudder import QualityAssuranceAirudder

    return QualityAssuranceAirudder(
        settings.QA_AIRUDDER_API_KEY,
        settings.QA_AIRUDDER_API_SECRET_KEY,
        settings.QA_AIRUDDER_API_BASE_URL,
    )

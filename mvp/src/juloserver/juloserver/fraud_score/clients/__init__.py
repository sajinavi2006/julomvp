from django.conf import settings

from juloserver.fraud_score.clients.finscore import FinscoreClient
from juloserver.fraud_score.clients.trust_decision import TrustDecisionClient


def get_bonza_client(bonza_feature=None):
    from .bonza_client import BonzaClient
    from juloserver.julo.models import FeatureSetting
    from juloserver.julo.constants import FeatureNameConst
    from juloserver.fraud_score.constants import BonzaConstants

    if not bonza_feature:
        bonza_feature = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.BONZA_LOAN_SCORING).last()

    APPLICATION = "/events/application"
    LOAN_TRANSACTION = "/events/loan-transaction"
    LOAN_PAYMENT = "/events/loan-payment"
    LOAN_SCORING = "/fraud-scoring/loan-transaction-scoring"

    def build_url(path):
        url = settings.BONZA_API_BASE_URL + path
        return url

    api_urls = {
        'application': build_url(APPLICATION),
        'loan_transaction': build_url(LOAN_TRANSACTION),
        'loan_payment': build_url(LOAN_PAYMENT),
        'loan_scoring': build_url(LOAN_SCORING),
        'inhouse_loan_scoring': settings.BONZA_INHOUSE_LOAN_SCORING_URL}

    timeout_params = BonzaConstants.API_TIMEOUTS
    if bonza_feature:
        timeout_params = bonza_feature.parameters.get(
            'timeout_parameters', BonzaConstants.API_TIMEOUTS)
    return BonzaClient(settings.BONZA_API_KEY, api_urls, timeout_params)


def get_trust_decision_client():
    return TrustDecisionClient(
        settings.TRUST_DECISION_PARTNER_CODE,
        settings.TRUST_DECISION_PARTNER_KEY,
        settings.TRUST_DECISION_HOST_URL,
    )


def get_finscore_client():
    return FinscoreClient(
        settings.TRUST_DECISION_PARTNER_CODE,
        settings.TRUST_DECISION_PARTNER_KEY,
        settings.FINSCORE_HOST_URL,
    )

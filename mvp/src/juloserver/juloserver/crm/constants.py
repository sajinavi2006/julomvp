from juloserver.julo.models import ApplicationStatusCodes

AGENT_USER_GROUP = [
    'document_verifier',
    'bo_full',
    'bo_data_verifier',
    'bo_credit_analyst',
    'bo_finance',
    'bo_general_cs',
    'bo_sd_verifier',
    'collection_agent_2',
    'collection_agent_3',
    'collection_agent_4',
    'collection_agent_5',
    'collection_supervisor',
    'freelance',
    'collection_team_leader',
    'collection_area_coordinator',
]

EMAIL_STATUSES = [121, 132, 138, 122, 130, 131, 135]
SKIPTRACE_STATUSES = [121, 122, 130, 131, 132, 138, 141, 180]
CA_CALCULATION_STATUSES = [130, 140, 141, 142, 143, 160, 161]
DISBURSEMENT_STATUSES = [ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
                         ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
                         ApplicationStatusCodes.NAME_VALIDATE_FAILED]

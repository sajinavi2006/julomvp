from builtins import object
from ...statuses import ApplicationStatusCodes


# follow this pattern for create a new workflow

# classname must be camelize from filename with 'Schema' postfix
class LegacySchema(object):
    NAME = 'LegacyWorkflow'
    DESC = 'this is a default workflow for existing application which has null workflow_id'
    HANDLER = NAME + 'Handler'
    PATH_TYPES = ('happy', 'detour', 'graveyard')


    # Happy Paths
    happy_paths = (
        {
            # 0
            'origin_status': ApplicationStatusCodes.NOT_YET_CREATED,
            'allowed_paths': (
                {
                    # happy path
                    'end_status': ApplicationStatusCodes.FORM_CREATED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
                {
                    # happy path, pre app revamp
                    'end_status': ApplicationStatusCodes.FORM_SUBMITTED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 100
            'origin_status': ApplicationStatusCodes.FORM_CREATED,
            'allowed_paths': (
                {
                    # happy path
                    'end_status': ApplicationStatusCodes.FORM_SUBMITTED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
                {
                    'end_status': ApplicationStatusCodes.FORM_PARTIAL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 105
            'origin_status': ApplicationStatusCodes.FORM_PARTIAL,
            'allowed_paths': (
                {
                    # happy path
                    'end_status': ApplicationStatusCodes.FORM_PARTIAL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
                {
                    # happy path
                    'end_status': ApplicationStatusCodes.FORM_SUBMITTED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 110
            'origin_status': ApplicationStatusCodes.FORM_SUBMITTED,
            'allowed_paths': (
                {
                    # happy path
                    'end_status': ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 120
            'origin_status': ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            'allowed_paths': (
                {
                    # happy path
                    'end_status': ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 121
            'origin_status': ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            'allowed_paths': (
                {
                    # happy path
                    'end_status': ApplicationStatusCodes.DOCUMENTS_VERIFIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
                {
                    'end_status': ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 122
            'origin_status': ApplicationStatusCodes.DOCUMENTS_VERIFIED,
            'allowed_paths': (
                {
                    # happy path
                    'end_status': ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 123
            'origin_status': ApplicationStatusCodes.PRE_REJECTION,
            'allowed_paths': (
                {
                    # happy path
                    'end_status': ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {  # 129
            'origin_status': ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.PARTNER_APPROVED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 124
            'origin_status': ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
                {
                    'end_status': ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': False,
                    'type': PATH_TYPES[0]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICANT_CALLS_ONGOING,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 126
            'origin_status': ApplicationStatusCodes.APPLICANT_CALLS_ONGOING,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 130
            'origin_status': ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 135
            'origin_status': ApplicationStatusCodes.APPLICATION_DENIED,
            'allowed_paths': (
                {
                    # redirect to 189 only for partner loan triggered
                    'end_status': ApplicationStatusCodes.PARTNER_APPROVED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 137
            'origin_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
            'allowed_paths': (
                {
                    # redirect to 189 only for partner loan triggered
                    'end_status': ApplicationStatusCodes.PARTNER_APPROVED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 141
            'origin_status': ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 160
            'origin_status': ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
            'allowed_paths': (
                {
                    # happy path
                    'end_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
                    'customer_accessible': True,
                    'agent_accessible': False,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 163
            'origin_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.FUND_DISBURSAL_ONGOING,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
                {
                    'end_status': ApplicationStatusCodes.NAME_VALIDATE_ONGOING,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 164
            'origin_status': ApplicationStatusCodes.NAME_VALIDATE_ONGOING,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.LENDER_APPROVAL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
                {
                    'end_status': ApplicationStatusCodes.FUND_DISBURSAL_ONGOING,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 165
            'origin_status': ApplicationStatusCodes.LENDER_APPROVAL,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
                {
                    'end_status': ApplicationStatusCodes.FUND_DISBURSAL_ONGOING,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 170
            'origin_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 131
            'origin_status': ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_RESUBMITTED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 132
            'origin_status': ApplicationStatusCodes.APPLICATION_RESUBMITTED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.DOCUMENTS_VERIFIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
                {
                    'end_status': ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
                    'customer_accessible': False,
                    'agent_accessible': False,
                    'type': PATH_TYPES[0]
                }
            )
        },
        {
            # 138
            'origin_status': ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 140
            'origin_status': ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
                    'customer_accessible': True,
                    'agent_accessible': False,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 161
            'origin_status': ApplicationStatusCodes.ACTIVATION_CALL_FAILED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 162
            'origin_status': ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 172
            'origin_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.DOWN_PAYMENT_PAID,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 173
            'origin_status': ApplicationStatusCodes.DOWN_PAYMENT_PAID,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 175
            'origin_status': ApplicationStatusCodes.NAME_VALIDATE_FAILED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.NAME_VALIDATE_ONGOING,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 176
            'origin_status': ApplicationStatusCodes.KYC_IN_PROGRESS,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 177
            'origin_status': ApplicationStatusCodes.FUND_DISBURSAL_ONGOING,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 181
            'origin_status': ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },

        {
            # 134
            'origin_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.FORM_PARTIAL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
                {
                    'end_status': ApplicationStatusCodes.FORM_SUBMITTED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
                {
                    'end_status': ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
                {
                    'end_status': ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
                {
                    'end_status': ApplicationStatusCodes.DOCUMENTS_VERIFIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
                {
                    'end_status': ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
                {
                    'end_status': ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
    )

    # Graveyard Paths
    graveyard_paths = (
        {
            # 0
            'origin_status': ApplicationStatusCodes.NOT_YET_CREATED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 100
            'origin_status': ApplicationStatusCodes.FORM_CREATED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 105
            'origin_status': ApplicationStatusCodes.FORM_PARTIAL,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 110
            'origin_status': ApplicationStatusCodes.FORM_SUBMITTED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 120
            'origin_status': ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 121
            'origin_status': ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 122
            'origin_status': ApplicationStatusCodes.DOCUMENTS_VERIFIED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 123
            'origin_status': ApplicationStatusCodes.PRE_REJECTION,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {  # 129
            'origin_status': ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )

        },
        {
            # 124
            'origin_status': ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 126
            'origin_status': ApplicationStatusCodes.APPLICANT_CALLS_ONGOING,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 130
            'origin_status': ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 135
            'origin_status': ApplicationStatusCodes.APPLICATION_DENIED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    # redirect to 137 only for partner loan triggered
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 137
            'origin_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
            'allowed_paths': (
                {
                    # redirect to 135 only for partner loan triggered
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 133
            'origin_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 141
            'origin_status': ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 160
            'origin_status': ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 163
            'origin_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 170
            'origin_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 131
            'origin_status': ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 132
            'origin_status': ApplicationStatusCodes.APPLICATION_RESUBMITTED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 138
            'origin_status': ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 140
            'origin_status': ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.OFFER_EXPIRED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 161
            'origin_status': ApplicationStatusCodes.ACTIVATION_CALL_FAILED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 162
            'origin_status': ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 172
            'origin_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.DOWN_PAYMENT_EXPIRED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 173
            'origin_status': ApplicationStatusCodes.DOWN_PAYMENT_PAID,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },

                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 175
            'origin_status': ApplicationStatusCodes.NAME_VALIDATE_FAILED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 177
            'origin_status': ApplicationStatusCodes.FUND_DISBURSAL_ONGOING,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 181
            'origin_status': ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 134
            'origin_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    'end_status': ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
    )
    # Detour Paths
    detour_paths = (
        {
            # 110
            'origin_status': ApplicationStatusCodes.FORM_SUBMITTED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.PRE_REJECTION,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
                {
                    # for when the application was first created
                    'end_status': ApplicationStatusCodes.FORM_SUBMITTED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
                {
                    # redirect to 129
                    'end_status': ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 120
            'origin_status': ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.PRE_REJECTION,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
                {
                    'end_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 121
            'origin_status': ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 122
            'origin_status': ApplicationStatusCodes.DOCUMENTS_VERIFIED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 123
            'origin_status': ApplicationStatusCodes.PRE_REJECTION,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.PRE_REJECTION,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 124
            'origin_status': ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 130
            'origin_status': ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 135
            'origin_status': ApplicationStatusCodes.APPLICATION_DENIED,
            'allowed_paths': (
                {
                    # redirect to 129 only for partner loan triggered
                    'end_status': ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 137
            'origin_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
            'allowed_paths': (
                {
                    # redirect to 129 only for partner loan triggered
                    'end_status': ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 141
            'origin_status': ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.ACTIVATION_CALL_FAILED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 160
            'origin_status': ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 163
            'origin_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 164
            'origin_status': ApplicationStatusCodes.NAME_VALIDATE_ONGOING,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 165
            'origin_status': ApplicationStatusCodes.LENDER_APPROVAL,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 170
            'origin_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
                {
                    'end_status': ApplicationStatusCodes.KYC_IN_PROGRESS,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },

        {
            # 106
            'origin_status': ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 111
            'origin_status': ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 131
            'origin_status': ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 132
            'origin_status': ApplicationStatusCodes.APPLICATION_RESUBMITTED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 136
            'origin_status': ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 138
            'origin_status': ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 139
            'origin_status': ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 140
            'origin_status': ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 143
            'origin_status': ApplicationStatusCodes.OFFER_EXPIRED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 161
            'origin_status': ApplicationStatusCodes.ACTIVATION_CALL_FAILED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 162
            'origin_status': ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 171
            'origin_status': ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 175
            'origin_status': ApplicationStatusCodes.NAME_VALIDATE_FAILED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
        {
            # 181
            'origin_status': ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },

        {
            # 134
            'origin_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
                {
                    'end_status': ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
    )

    status_nodes = None
    # status_nodes = ({
    #                     # 100
    #                     'destination_status': ApplicationStatusCodes.FORM_CREATED,
    #                     'handler': NAME + 'Node100Handler'
    #                 },
    #                 {
    #                     # 105
    #                     'destination_status': ApplicationStatusCodes.FORM_PARTIAL,
    #                     'handler': NAME + 'Node105Handler'
    #                 },
    #                 {
    #                     # 106
    #                     'destination_status': ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
    #                     'handler': NAME + 'Node106Handler'
    #                 },
    #                 {
    #                     # 111
    #                     'destination_status': ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
    #                     'handler': NAME + 'Node111Handler'
    #                 },
    #                 {
    #                     # 120
    #                     'destination_status': ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
    #                     'handler': NAME + 'Node120Handler'
    #                 },
    #                 {
    #                     # 122
    #                     'destination_status': ApplicationStatusCodes.DOCUMENTS_VERIFIED,
    #                     'handler': NAME + 'Node122Handler'
    #                 },
    #                 {
    #                     # 130
    #                     'destination_status': ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
    #                     'handler': NAME + 'Node130Handler'
    #                 },
    #                 {
    #                     # 131
    #                     'destination_status': ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
    #                     'handler': NAME + 'Node131Handler'
    #                 },
    #                 {
    #                     # 132
    #                     'destination_status': ApplicationStatusCodes.APPLICATION_RESUBMITTED,
    #                     'handler': NAME + 'Node132Handler'
    #                 },
    #                 {
    #                     # 133
    #                     'destination_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
    #                     'handler': NAME + 'Node133Handler'
    #                 },
    #                 {
    #                     # 134
    #                     'destination_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
    #                     'handler': NAME + 'Node134Handler'
    #                 },
    #                 {
    #                     # 135
    #                     'destination_status': ApplicationStatusCodes.APPLICATION_DENIED,
    #                     'handler': NAME + 'Node135Handler'
    #                 },
    #                 {
    #                     # 136
    #                     'destination_status': ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
    #                     'handler': NAME + 'Node136Handler'
    #                 },
    #                 {
    #                     # 137
    #                     'destination_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
    #                     'handler': NAME + 'Node137Handler'
    #                 },
    #                 {
    #                     # 138
    #                     'destination_status': ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
    #                     'handler': NAME + 'Node138Handler'
    #                 },
    #                 {
    #                     # 139
    #                     'destination_status': ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
    #                     'handler': NAME + 'Node139Handler'
    #                 },
    #                 {
    #                     # 140
    #                     'destination_status': ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
    #                     'handler': NAME + 'Node140Handler'
    #                 },
    #                 {
    #                     # 141
    #                     'destination_status': ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
    #                     'handler': NAME + 'Node141Handler'
    #                 },
    #                 {
    #                     # 142
    #                     'destination_status': ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
    #                     'handler': NAME + 'Node142Handler'
    #                 },
    #                 {
    #                     # 143
    #                     'destination_status': ApplicationStatusCodes.OFFER_EXPIRED,
    #                     'handler': NAME + 'Node143Handler'
    #                 },
    #                 {
    #                     # 160
    #                     'destination_status': ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
    #                     'handler': NAME + 'Node160Handler'
    #                 },
    #                 {
    #                     # 161
    #                     'destination_status': ApplicationStatusCodes.ACTIVATION_CALL_FAILED,
    #                     'handler': NAME + 'Node161Handler'
    #                 },
    #                 {
    #                     # 162
    #                     'destination_status': ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,
    #                     'handler': NAME + 'Node162Handler'
    #                 },
    #                 {
    #                     # 163
    #                     'destination_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
    #                     'handler': NAME + 'Node163Handler'
    #                 },
    #                 {
    #                     # 170
    #                     'destination_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
    #                     'handler': NAME + 'Node170Handler'
    #                 },
    #                 {
    #                     # 171
    #                     'destination_status': ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
    #                     'handler': NAME + 'Node171Handler'
    #                 },
    #                 {
    #                     # 180
    #                     'destination_status': ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
    #                     'handler': NAME + 'Node180Handler'
    #                 },
    #
    # )

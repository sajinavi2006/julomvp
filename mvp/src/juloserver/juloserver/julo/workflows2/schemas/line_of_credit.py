from builtins import object
from ...statuses import ApplicationStatusCodes


# follow this pattern for create a new workflow

# classname must be camelize from filename with 'Schema' postfix
class LineOfCreditSchema(object):
    NAME = 'LineOfCreditWorkflow'
    DESC = 'this is a workflow for line of credit'
    HANDLER = NAME + 'Handler'
    PATH_TYPES = ('happy', 'detour', 'graveyard')

# Happy Paths
    happy_paths = (
        {
            # 105
            'origin_status': ApplicationStatusCodes.FORM_PARTIAL,
            'allowed_paths': (
                {
                    # 120
                    'end_status': ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
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
                    # 120
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
                    # 121
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
                    # 141
                    'end_status': ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
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
                    # 160
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
                    # 163
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
                    # 190
                    'end_status': ApplicationStatusCodes.LOC_APPROVED,
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
                    # 132
                    'end_status': ApplicationStatusCodes.APPLICATION_RESUBMITTED,
                    'customer_accessible': True,
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
                    # 141
                    'end_status': ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
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
                    # 163
                    'end_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
                    'customer_accessible': True,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },

    )

# detour
    detour_paths = (
        {
            # 163
            'origin_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
            'allowed_paths': (
                {
                    # 162
                    'end_status': ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,
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
                    # 131
                    'end_status': ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
    )

    # graveyard
    graveyard_paths = (
        {
            # 105
            'origin_status': ApplicationStatusCodes.FORM_PARTIAL,
            'allowed_paths': (
                {
                    #111
                    'end_status': ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    # 137
                    'end_status': ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
    )

    status_nodes = ({
                        # 120
                        'destination_status': ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
                        'handler': 'LineOfCreditWorkflowNode120Handler'
                    },
                    {
                        # 190
                        'destination_status': ApplicationStatusCodes.LOC_APPROVED,
                        'handler': 'LineOfCreditWorkflowNode190Handler'
                    },
    )
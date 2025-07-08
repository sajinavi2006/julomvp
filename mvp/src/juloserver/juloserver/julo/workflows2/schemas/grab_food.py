from builtins import object
from ...statuses import ApplicationStatusCodes


# follow this pattern for create a new workflow

# classname must be camelize from filename with 'Schema' postfix
class GrabFoodSchema(object):
    NAME = 'GrabFoodWorkflow'
    DESC = 'this is a workflow for grab food modal ramadhan'
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
                    # 125
                    'end_status': ApplicationStatusCodes.CALL_ASSESSMENT,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 125
            'origin_status': ApplicationStatusCodes.CALL_ASSESSMENT,
            'allowed_paths': (
                {
                    # 134
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
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
                    # 170
                    'end_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
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
                    # 180
                    'end_status': ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                    'customer_accessible': True,
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
                    # 170
                    'end_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
    )

# detour
    detour_paths = (
        {
            # 170
            'origin_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
            'allowed_paths': (
                {
                    # 175
                    'end_status': ApplicationStatusCodes.NAME_VALIDATE_FAILED,
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
                    'end_status': ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
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
                    # 135
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
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
                    # 135
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
            )
        },
        {
            # 125
            'origin_status': ApplicationStatusCodes.CALL_ASSESSMENT,
            'allowed_paths': (
                {
                    # 135
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    # 133
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
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
        {
            # 134
            'origin_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
            'allowed_paths': (
                {
                    # 135
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    # 133
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
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
        {
            # 141
            'origin_status': ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            'allowed_paths': (
                {
                    # 135
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
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
        {
            # 163
            'origin_status': ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
            'allowed_paths': (
                {
                    # 135
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[2]
                },
                {
                    # 133
                    'end_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
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
        {
            # 175
            'origin_status': ApplicationStatusCodes.NAME_VALIDATE_FAILED,
            'allowed_paths': (
                {
                    # 135
                    'end_status': ApplicationStatusCodes.APPLICATION_DENIED,
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

    status_nodes = ()


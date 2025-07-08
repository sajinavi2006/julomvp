from builtins import str
from builtins import object
from ...statuses import ApplicationStatusCodes


# follow this pattern for create a new workflow

# classname must be camelize from filename with 'Schema' postfix
class SubmittingFormSchema(object):
    NAME = 'SubmittingFormWorkflow'
    DESC = 'this is a workflow for initial application '
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
    )
    # Detour Paths
    detour_paths = (
        {
            # 105
            'origin_status': ApplicationStatusCodes.FORM_PARTIAL,
            'allowed_paths': (
                {
                    # for when the application was first created
                    'end_status': ApplicationStatusCodes.FORM_PARTIAL,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
                {
                    # handle transition app v3
                    'end_status': ApplicationStatusCodes.FORM_CREATED,
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
            # 134
            'origin_status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
            'allowed_paths': (
                {
                    'end_status': ApplicationStatusCodes.FORM_PARTIAL,
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
                    # for when the application was first created
                    'end_status': ApplicationStatusCodes.FORM_SUBMITTED,
                    'customer_accessible': False,
                    'agent_accessible': True,
                    'type': PATH_TYPES[1]
                },
            )
        },
    )

    status_nodes = ({
                        # 110
                        'destination_status': ApplicationStatusCodes.FORM_SUBMITTED,
                        'handler': NAME + 'Node'+ str(ApplicationStatusCodes.FORM_SUBMITTED) +'Handler'
                    },
                    {
                        # 105
                        'destination_status': ApplicationStatusCodes.FORM_PARTIAL,
                        'handler': NAME + 'Node' + str(ApplicationStatusCodes.FORM_PARTIAL) + 'Handler'
                    },
    )

from builtins import object

from juloserver.julo.statuses import ApplicationStatusCodes


# follow this pattern for create a new workflow

# classname must be camelize from filename with 'Schema' postfix


class JuloOneSchema(object):
    NAME = 'JuloOneWorkflow'
    DESC = 'this is a workflow for J1 '
    HANDLER = NAME + 'Handler'
    PATH_TYPES = ('happy', 'detour', 'graveyard')

    happy_paths = (
        {
            # 110
            'origin_status': ApplicationStatusCodes.FORM_SUBMITTED,
            'allowed_paths': (
                {
                    # 185
                    'end_status': ApplicationStatusCodes.CUSTOMER_ON_DELETION,
                    'customer_accessible': True,
                    'agent_accessible': False,
                    'type': PATH_TYPES[0]
                },
                {
                    # 186
                    'end_status': ApplicationStatusCodes.CUSTOMER_DELETED,
                    'customer_accessible': True,
                    'agent_accessible': True,
                    'type': PATH_TYPES[0]
                },
            )
        },
        {
            # 185
            'origin_status': ApplicationStatusCodes.CUSTOMER_ON_DELETION,
            'allowed_paths': (
                {
                    # 110
                    'end_status': ApplicationStatusCodes.FORM_SUBMITTED,
                    'customer_accessible': True,
                    'agent_accessible': False,
                    'type': PATH_TYPES[0]
                },
            )
        },
    )

    detour_paths = ()

    graveyard_paths = ()

    status_nodes = ()

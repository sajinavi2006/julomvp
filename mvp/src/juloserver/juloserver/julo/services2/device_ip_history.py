from juloserver.julo.models import DeviceIpHistory


def get_application_submission_ip_history(application):
    """
    Get the DeviceIPHistory for registration flow.

    Args:
        application (Application): the application object with id and customer_id available

    Returns:
        DeviceIpHistory: DeviceIpHistory Object.
    """
    paths = (
        '/api/v2/application/{}/'.format(application.id),
        '/api/v3/application/{}/'.format(application.id),
        '/api/application_form/v1/application/{}'.format(application.id),
        '/api/application_form/v2/application/{}'.format(application.id),
    )
    return DeviceIpHistory.objects.filter(
        customer=application.customer_id,
        path__in=paths,
    ).order_by('-cdate').first()

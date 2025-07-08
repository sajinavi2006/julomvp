from juloserver.julo.models import Application


def get_applications_dictionary(loans):
    application_dict = {}
    application_ids = set()

    for loan in loans:
        application_ids.add(loan.application_id2)

    applications = Application.objects.filter(id__in=application_ids).select_related("creditscore")

    for app in applications:
        application_dict[app.id] = {"application": app, "creditscore": app.creditscore}

    return application_dict

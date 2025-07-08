class GetActiveApplicationMixin(object):
    def get_active_application(self):
        '''
        Getting active application, also covers for J1 and JTurbo upgrade case
        '''
        from juloserver.julo.models import (
            ApplicationUpgrade,
            Application,
        )
        from juloserver.julo.statuses import ApplicationStatusCodes

        applications = self.application_set.regular_not_deletes().order_by('-cdate')
        if not applications:
            return None

        # Find for the application upgrade
        application_upgrade = ApplicationUpgrade.objects.filter(
            application_id__in=list(applications.values_list('id', flat=True)),
            is_upgrade=1,
        ).last()

        # Not having application upgrade: Return the latest application
        if not application_upgrade:
            return applications.first()

        # Get upgraded application if status approved
        application_j1 = Application.objects.get_or_none(
            pk=application_upgrade.application_id,
            application_status_id=ApplicationStatusCodes.LOC_APPROVED,
        )
        if application_j1:
            return application_j1

        # return application JTurbo as main application if j1 not approved yet
        return Application.objects.get_or_none(
            pk=application_upgrade.application_id_first_approval,
        )

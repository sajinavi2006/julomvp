import time

from collections import defaultdict
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    FDCInquiry,
    Partner,
    Application,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.partnership.constants import PartnershipPreCheckFlag
from juloserver.partnership.models import PartnershipApplicationFlag
from juloserver.partnership.tasks import partnership_run_fdc_inquiry_for_registration


def retrieve_applications_with_error_fdc_status_by_partner(partner_id: int) -> list:
    partner = Partner.objects.filter(pk=partner_id).last()
    if not partner:
        raise JuloException('Partner not found')

    list_application_with_error_fdc = []

    list_application_flag = PartnershipApplicationFlag.objects.filter(
        name=PartnershipPreCheckFlag.PASSED_PRE_CHECK
    ).values_list('application_id', flat=True)

    application_datas = Application.objects.filter(
        partner_id=partner_id,
        application_status=ApplicationStatusCodes.FORM_CREATED,
        id__in=list_application_flag,
    ).values('id', 'ktp')

    mapping_applications = defaultdict(int)
    for application_data in application_datas.iterator():
        mapping_applications[application_data['id']] = application_data['ktp']

    get_all_applications = FDCInquiry.objects.filter(
        application_id__in=list(mapping_applications.keys()),
        inquiry_reason='1 - Applying loan via Platform',
        inquiry_status='error',
    ).values('id', 'application_id')

    if not get_all_applications:
        raise JuloException('applications not found')

    for application in get_all_applications:
        nik = mapping_applications.get(application['application_id'])
        fdc_inquiry_data = {
            'id': application['id'],  # ID Fdc inqury
            'nik': nik,
            'application_id': application['application_id'],
        }
        list_application_with_error_fdc.append(fdc_inquiry_data)
    return list_application_with_error_fdc


def retrieve_applications_with_error_fdc_status_by_application_xids(application_xids: list) -> list:
    application_datas = Application.objects.filter(
        application_xid__in=application_xids,
        application_status=ApplicationStatusCodes.FORM_CREATED,
    ).values('id', 'ktp')

    mapping_applications = defaultdict(int)
    for application_data in application_datas.iterator():
        mapping_applications[application_data['id']] = application_data['ktp']

    list_application_with_error_fdc = []
    get_all_applications = FDCInquiry.objects.filter(
        application_id__in=list(mapping_applications.keys()),
        inquiry_reason='1 - Applying loan via Platform',
        inquiry_status='error',
    ).values('id', 'application_id')

    if not get_all_applications:
        raise JuloException('applications not found')

    for application in get_all_applications:
        nik = mapping_applications.get(application['application_id'])
        fdc_inquiry_data = {
            'id': application['id'],  # ID Fdc inqury
            'nik': nik,
            'application_id': application['application_id'],
        }
        list_application_with_error_fdc.append(fdc_inquiry_data)
    return list_application_with_error_fdc


def rerun_fdc_inquiry_for_registration(
    list_applications: list,
    time_sleep: int = 3,
) -> None:
    counter = 0

    if not list_applications:
        raise JuloException('list_applications not found')

    for application in list_applications:
        counter += 1
        partnership_run_fdc_inquiry_for_registration.delay(application, 1)
        print(
            'Row {}, Process re-run FDC application: {}'.format(
                counter, application.get('application_id')
            )
        )
        time.sleep(time_sleep)

    print("Success rerun fdc inquiry")

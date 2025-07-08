import logging

from django.core.urlresolvers import reverse
from django.db import transaction
from django.db.models import CharField, Value
from django.utils import timezone

from juloserver.apiv2.models import EtlJob
from juloserver.application_flow.services import is_experiment_application
from juloserver.bpjs.services import Bpjs
from juloserver.julo.application_checklist import application_checklist_update
from juloserver.julo.constants import SkiptraceResultChoiceConst
from juloserver.julo.models import (
    Application,
    ApplicationCheckList,
    ApplicationCheckListComment,
    AwsFaceRecogLog,
    FaceRecognition,
    Image,
    SecurityNote,
    Skiptrace,
    SkiptraceHistory,
    SkiptraceResultChoice,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import get_allowed_application_statuses_for_ops
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.new_crm.constants.application_constants import CRMAppConstants
from juloserver.portal.core.templatetags.unit import show_filename
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.portal.object.loan_app.utils import get_list_history_all
from juloserver.application_flow.services import check_revive_mtl

logger = logging.getLogger(__name__)


def filter_app_statuses_crm(status_code, application):

    if not isinstance(application, Application):
        application = Application.objects.get_or_none(pk=application)

    # used to be in juloserver.portal.object.app_status.forms.py
    # now moved into this function
    status_choices = []
    allowed_statuses = get_allowed_application_statuses_for_ops(
        int(status_code.status_code), application)

    if allowed_statuses:
        face_recognition = FaceRecognition.objects.get_or_none(
            feature_name='face_recognition',
            is_active=True
        )
        passed_face_recog = AwsFaceRecogLog.objects.filter(
            application=application,
            is_quality_check_passed=True
        ).last()
        # check if not passed_face_recog delete allowed status 131
        if application.status == ApplicationStatusCodes.CALL_ASSESSMENT and \
                application.product_line_code in ProductLineCodes.lended_by_jtp():
            for idx, allowed_status in enumerate(allowed_statuses):
                if face_recognition:
                    if (
                        passed_face_recog and
                        allowed_status.code == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
                    ):
                        allowed_statuses.pop(idx)
                    elif (
                        not passed_face_recog and
                        allowed_status.code == ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
                    ):
                        allowed_statuses.pop(idx)
                else:
                    if (
                        allowed_status.code == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
                    ):
                        allowed_statuses.pop(idx)
        if application.status == ApplicationStatusCodes.NAME_VALIDATE_FAILED:
            for idx, allowed_status in enumerate(allowed_statuses):
                if (
                    not check_revive_mtl(application)
                    and allowed_status.code == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
                ):
                    allowed_statuses.pop(idx)
                if (
                    check_revive_mtl(application)
                    and allowed_status.code == ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL
                ):
                    allowed_statuses.pop(idx)

        status_choices = [
            [status.code, "%s - %s" % (status.code, status.desc)] for status in allowed_statuses
        ]
    status_choices.insert(0, [None, '-- Pilih --'])

    return allowed_statuses, status_choices


def create_application_checklist_comment_data(application, comment):
    with transaction.atomic():
        ApplicationCheckListComment.objects.create(
            field_name=comment['field_name'], application=application,
            comment=comment['value'], group=comment['group'])


def get_application_status_histories(application):
    from juloserver.new_crm.serializers import AppStatusAndNoteHistorySerializer

    history_and_notes = get_list_history_all(application)

    security_note_list = (
        SecurityNote.objects.filter(
            customer=application.customer
        ).select_related('added_by').order_by('-cdate')
    )
    history_and_notes += security_note_list
    serializer = AppStatusAndNoteHistorySerializer(history_and_notes, many=True)
    return serializer.data


def get_image_list(application):
    result = []
    image_queryset = Image.objects.only(
        'id', 'url', 'image_type', 'image_status', 'service').filter(
        image_source=application.id)
    for img_obj in image_queryset:
        result.append({
            'img_id': img_obj.id,
            'img_type': img_obj.image_type,
            'img_url': img_obj.image_url,
            'img_resubmission': True if img_obj.image_status == Image.RESUBMISSION_REQ else False,
        })

    return result


def get_tab_list(application, groups):
    from juloserver.sdk.constants import PARTNER_LAKU6

    tabs_to_show = []
    tabs_to_show.append(CRMAppConstants.DVC)
    if groups.filter(name__in=[JuloUserRoles.BO_DATA_VERIFIER, JuloUserRoles.ADMIN_FULL]).exists():
        tabs_to_show.append(CRMAppConstants.SD)
    if not groups.filter(name__in=[JuloUserRoles.BO_OUTBOUND_CALLER_3rd_PARTY]).exists():
        tabs_to_show.append(CRMAppConstants.FIN)
    if groups.filter(name__in=[JuloUserRoles.ADMIN_FULL, JuloUserRoles.BO_FULL,
                     JuloUserRoles.BO_DATA_VERIFIER, JuloUserRoles.CS_TEAM_LEADER]).exists():
        tabs_to_show.append(CRMAppConstants.SECURITY)

    #Skiptrace tab check
    if application.status in CRMAppConstants.list_skiptrace_status:
        tabs_to_show.append(CRMAppConstants.ST)

    # Name Bank Validation tab check
    if is_experiment_application(application.id,'ExperimentUwOverhaul') \
            and application.is_julo_one():
        experiment_status = ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
    else:
        experiment_status = ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL

    add_nbv = False
    if application.is_julo_one:
        if application.status in \
            [experiment_status, ApplicationStatusCodes.NAME_BANK_VALIDATION_FAILED]:
            add_nbv = True
    elif application.is_julover and \
        application.status == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
        add_nbv = True
    if not add_nbv and application.partner and application.partner.name == PARTNER_LAKU6:
        add_nbv = True
    if add_nbv and application.status >= ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
        tabs_to_show.append(CRMAppConstants.NAME_BANK_VALIDATION)

    results = {}
    for tab in CRMAppConstants.app_details_tabs():
        results[tab] = True if tab in tabs_to_show else False
    return results


def get_application_scrape_data(application):
    """
    Get application scrape data for SD tab

    :param application: Application
    :return: a dictionary of BPJS and SD data. The return is ready to be consumed by FE.
    With this format. `is_sheet` means the url is excel can be viewed in 'app_status:sd_sheet'
        [
            {
                "type": "bpjs",
                "filename": "filname.pdf",
                "url": "<file-url>",
                "is_downloadable": True,
                "is_sheet": False,
                "is_viewable": False
            },
            {
                "type": "sd",
                "filename": "filname.pdf",
                "url": "<file-url>",
                "is_downloadable": False,
                "is_sheet": True,
                "is_viewable": True
            },
            {
                "type": "bank",
                "filename": "filname.pdf",
                "url": "<file-url>",
                "is_downloadable": True,
                "is_sheet": True,
                "is_viewable": True
            }
        ]
    """
    default_data = {
        "type": None,
        "filename": None,
        "url": None,
        "is_downloadable": False,
        "is_sheet": False,
        "is_viewable": False
    }
    sd_data = []

    # BPJS Data
    bpjs = Bpjs(application=application)
    if bpjs.is_scraped:
        sd_data.append({
            **default_data,
            "type": "bpjs",
            "filename": "BPJS_Report_{}.pdf".format(application.id),
            "url": reverse("bpjs:bpjs_pdf", args=[application.id]),
            "is_downloadable": True,
        })

    # SD Data
    sd_obj = application.device_scraped_data.last()
    if sd_obj and sd_obj.reports_xls_s3_url:
        sd_data.append({
            **default_data,
            "type": "sd",
            "filename": show_filename(sd_obj.reports_url),
            "url": sd_obj.reports_xls_s3_url,
            "is_viewable": True,
            "is_sheet": True
        })

    # Bank Data
    etl_job = EtlJob.objects.filter(
        application_id=application.id, status='load_success',
        data_type__in=['bca', 'mandiri', 'bni', 'bri']
    ).order_by('-cdate').first()
    if etl_job:
        bank_report_url = etl_job.get_bank_report_url()
        if bank_report_url:
            sd_data.append({
                **default_data,
                "type": "bank",
                "filename": show_filename(etl_job.s3_url_bank_report),
                "url": bank_report_url,
                "is_downloadable": True,
                "is_viewable": True,
                "is_sheet": True
            })

    return sd_data


def get_application_skiptrace_list(application):
    skiptrace_list = Skiptrace.objects.filter(customer_id=application.customer_id).order_by('id')
    return list(skiptrace_list)


def get_application_skiptrace_result_list():
    skiptrace_result_qs = SkiptraceResultChoice.objects.filter(
        name__in=SkiptraceResultChoiceConst.basic_skiptrace_result_list()
    ).order_by('id')

    return list(skiptrace_result_qs)

import logging
import json
import os
from django.db import transaction
from django.views.decorators.csrf import csrf_protect
from django.shortcuts import render
from datetime import datetime
from django.http import JsonResponse
from django.utils import timezone
from juloserver.portal.object import (
    julo_login_required,
    julo_login_required_group,
)
from django.shortcuts import redirect
from django.http.response import HttpResponseNotAllowed
from django.db.models import Case, When
from juloserver.cohort_campaign_automation.constants import CohortCampaignAutomationStatus
from juloserver.cohort_campaign_automation.models import (
    CollectionCohortCampaignAutomation,
    CollectionCohortCampaignEmailTemplate,
)
from juloserver.cohort_campaign_automation.services.services import (
    check_duplicate_campaign_name,
    DuplicatedException,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.cohort_campaign_automation.tasks import upload_file_cohort_campaign_automation
from juloserver.julo.models import FeatureSetting
from juloserver.minisquad.constants import FeatureNameConst
from django.utils.safestring import mark_safe

logger = logging.getLogger(__name__)


@julo_login_required
@julo_login_required_group(JuloUserRoles.COHORT_CAMPAIGN_EDITOR)
def create_cohort_campaign_automation(request):
    # show creation page
    template_name = 'cohort_campaign_automation/campaign_form.html'
    promo_blast_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.WAIVER_R4_PROMO_BLAST, is_active=True
    ).last()
    html_code = ''
    if promo_blast_fs:
        parameters = promo_blast_fs.parameters
        html_code = parameters.get('campaign_automation', {}).get('email_html')
    context = {'base_html_code': mark_safe(html_code)}
    return render(request, template_name, context)


@julo_login_required
@julo_login_required_group(JuloUserRoles.COHORT_CAMPAIGN_EDITOR)
@csrf_protect
def submit_cohort_campaign_automation(request):
    # submit data creation
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    banner_email = request.FILES.get('banner_email', None)
    csv_file = request.FILES.get('csv_file', None)
    try:
        with transaction.atomic():
            campaign_name = data.get('campaign_name')
            if not data.get('is_edit'):
                exist_data = check_duplicate_campaign_name(campaign_name)
                if exist_data:
                    raise DuplicatedException(
                        'Pastikan nama campaign tidak sama dengan campaign yang lain'
                    )

            start_date = None
            end_date = None
            email_blast_date = None
            additional_email_blast_dates = []
            if data.get('campaign_start_period'):
                start_date = datetime.strptime(data.get('campaign_start_period'), "%Y-%m-%d")
            if data.get('campaign_end_period'):
                end_date = datetime.strptime(data.get('campaign_end_period'), "%Y-%m-%d")
            if data.get('email_blast_date'):
                email_blast_date = datetime.strptime(
                    data.get('email_blast_date'), "%Y-%m-%d %H:%M:%S"
                )
            index = 0
            while "email_schedules[%d]" % index in request.POST:
                additional_email_blast_dates.append(
                    datetime.strptime(data.get("email_schedules[%d]" % index), "%Y-%m-%d %H:%M:%S")
                )
                index += 1

            status = CohortCampaignAutomationStatus.SCHEDULED
            email_template = None
            campaign_data_dict = dict(
                campaign_name=campaign_name,
                start_date=start_date,
                end_date=end_date,
                status=status,
                created_by=request.user.username,
            )
            email_data_dict = dict(
                email_blast_date=email_blast_date,
                additional_email_blast_dates=additional_email_blast_dates,
                email_domain=data.get('email_domain'),
                subject=data.get('subject_email'),
                content_top=data.get('body_top_email'),
                content_middle=data.get('body_mid_email'),
                content_footer=data.get('body_footer_email')
            )
            if data.get('is_edit'):
                cohort_campaign_automation = CollectionCohortCampaignAutomation.objects.filter(
                    pk=data.get('campaign_id')
                ).last()
                if cohort_campaign_automation.campaign_name != campaign_name:
                    exist_data = check_duplicate_campaign_name(campaign_name)
                    if exist_data:
                        raise DuplicatedException(
                            'Pastikan nama campaign tidak sama dengan campaign yang lain'
                        )

                cohort_campaign_automation.update_safely(**campaign_data_dict)
                # update email template
                qs_email = CollectionCohortCampaignEmailTemplate.objects.filter(
                    campaign_automation=cohort_campaign_automation
                )
                qs_email.update(**email_data_dict)
                email_template = qs_email.last()
            else:
                campaign_data_dict.update(program_type='-')
                cohort_campaign_automation = CollectionCohortCampaignAutomation.objects.create(
                    **campaign_data_dict
                )
                # insert data for cohort campaign email template
                email_data_dict.update(campaign_automation=cohort_campaign_automation)
                email_template = CollectionCohortCampaignEmailTemplate.objects.create(
                    **email_data_dict
                )
            if banner_email:
                # handle banner email and upload to oss
                banner_email = request.FILES['banner_email']
                _, file_extension = os.path.splitext(banner_email.name)
                remote_name = "cohort_campaign_automation/banner_email/{}{}".format(
                    data.get('campaign_name') + '_' + str(email_template.id), file_extension
                )
                upload_file_cohort_campaign_automation.delay(
                    email_template.id, banner_email.read(), remote_name
                )
            if csv_file:
                # handle csv file and upload to oss
                csv_file = request.FILES['csv_file']
                _, file_extension = os.path.splitext(csv_file.name)
                remote_name = "cohort_campaign_automation/csv_file/{}{}".format(
                    data.get('campaign_name') + '_' + str(cohort_campaign_automation.id),
                    file_extension,
                )
                upload_file_cohort_campaign_automation.delay(
                    cohort_campaign_automation.id, csv_file.read(), remote_name
                )
    except DuplicatedException as e:
        return JsonResponse(
            {
                "status": "failed",
                "message": str(e),
            },
            status=400,
        )
    except Exception as e:
        logger.error(
            {
                "action": "submit_cohort_campaign_automation",
                "error_message": str(e),
            }
        )
        return JsonResponse(
            {
                "status": "failed",
                "message": str(e),
            },
            status=500,
        )
    else:
        return JsonResponse(
            {
                'status': 'success',
                'message': 'Data berhasil disimpan',
            }
        )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COHORT_CAMPAIGN_EDITOR)
def cohort_campaign_automation_list(request):
    # show page list of cohort campaign
    template_name = 'cohort_campaign_automation/campaign_list.html'
    context = {}
    return render(request, template_name, context)


@julo_login_required
@csrf_protect
def ajax_cohort_campaign_automation_list_view(request):
    # logic for pagination list of cohort campaign
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])

    max_per_page = int(request.GET.get('max_per_page'))
    count_page = 0
    try:
        page = int(request.GET.get('page'))
    except Exception:
        page = 1

    qs = CollectionCohortCampaignAutomation.objects.all().order_by('-cdate')
    primary_key = 'id'
    three_next_pages = max_per_page * (page + 2) + 1
    limit = max_per_page * page
    offset = limit - max_per_page

    result_ids = qs.values_list(primary_key, flat=True)
    result = result_ids[offset:three_next_pages]
    cohort_campaign_ids = list(result)
    cohort_campaign_ids_1page = cohort_campaign_ids[:max_per_page]
    count_cohort_campaign = len(cohort_campaign_ids)
    count_page = (
        page
        + (count_cohort_campaign // max_per_page)
        + (count_cohort_campaign % max_per_page > 0)
        - 1
    )
    if count_cohort_campaign == 0:
        count_page = page

    # this preserved is needed because random order by postgresql/django
    preserved = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(result)])

    cohort_campaign_list = list(
        qs.filter(**{primary_key + '__in': cohort_campaign_ids_1page})
        .order_by(preserved)
        .values(
            'campaign_name',
            'created_by',
            'start_date',
            'end_date',
            'program_type',
            'status',
        )
    )

    return JsonResponse(
        {
            'status': 'success',
            'cohort_automation_list': cohort_campaign_list,
            'count_page': count_page,
            'current_page': page,
        },
        safe=False,
    )


@julo_login_required
@csrf_protect
def cancel_status_cohort_campaign_automtion(request):
    # change cohort campaign status to cancel
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    try:
        CollectionCohortCampaignAutomation.objects.filter(
            campaign_name=data.get('campaign_name')
        ).update(status=CohortCampaignAutomationStatus.CANCELED)
    except Exception as e:
        logger.error(
            {
                "action": "cancel_status_cohort_campaign_automtion",
                "error_message": str(e),
            }
        )
        return JsonResponse(
            {'status': 'failed', 'message': "Gagal merubah status ke cancel"},
            status=400,
            safe=False,
        )

    return JsonResponse({'status': 'success', 'message': 'Status berhasil diubah'}, safe=False)


@julo_login_required
@csrf_protect
def edit_cohort_campaign_automation(request, campaign_name):
    cohort_campaign_automation = CollectionCohortCampaignAutomation.objects.get_or_none(
        campaign_name=campaign_name
    )
    if not cohort_campaign_automation:
        return redirect(
            '/cohort-campaign-automation/list/?message=campaign name %s tidak ditemukan'
            % campaign_name
        )

    promo_blast_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.WAIVER_R4_PROMO_BLAST, is_active=True
    ).last()
    html_code = ''
    if promo_blast_fs:
        parameters = promo_blast_fs.parameters
        html_code = parameters.get('campaign_automation', {}).get('email_html')

    email_template = CollectionCohortCampaignEmailTemplate.objects.get_or_none(
        campaign_automation=cohort_campaign_automation.id
    )
    template_name = 'cohort_campaign_automation/campaign_form.html'
    context = {
        'cohort_campaign': cohort_campaign_automation,
        'email_template': email_template,
        'base_html_code': mark_safe(html_code),
    }
    context['cohort_campaign'].start_date = context['cohort_campaign'].start_date.strftime(
        '%Y-%m-%d'
    )
    context['cohort_campaign'].end_date = context['cohort_campaign'].end_date.strftime('%Y-%m-%d')
    context['email_template'].email_blast_date = timezone.localtime(
        context['email_template'].email_blast_date
    ).strftime('%Y-%m-%d %H:%M:%S')
    context['email_template'].additional_email_blast_dates = json.dumps(
        [
            {
                "id": "email_blast_date_%d" % (i + 1),
                "date": timezone.localtime(date).strftime('%Y-%m-%d %H:%M:%S'),
            }
            for i, date in enumerate(context['email_template'].additional_email_blast_dates)
        ],
        ensure_ascii=False,
    )
    print(context)

    return render(request, template_name, context)

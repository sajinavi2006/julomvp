import json
import os
from datetime import datetime, timedelta

from babel.dates import format_date
from django.conf import settings
from django.db import transaction
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from rest_framework.views import APIView

from juloserver.collection_hi_season.constants import CampaignBanner
from juloserver.julo.models import Image, Partner
from juloserver.julo.utils import upload_file_to_oss
from juloserver.portal.core import functions
from juloserver.portal.object import julo_login_required, julo_login_required_multigroup
from juloserver.standardized_api_response.utils import success_response
from juloserver.streamlined_communication.models import InfoCardProperty

from .constants import (
    CampaignCardProperty,
    CampaignCommunicationPlatform,
    CampaignStatus,
)
from .models import (
    CollectionHiSeasonCampaign,
    CollectionHiSeasonCampaignBanner,
    CollectionHiSeasonCampaignCommsSetting,
)
from .serializers import PartnerSerializer
from .services import get_dpd_from_payment_terms


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'product_manager'])
def collection_hi_season_campaign_list(request):
    template_name = 'collection_hi_season/campaign_list.html'
    data = {
        'campaign_list': CollectionHiSeasonCampaign.objects.filter(
            campaign_status__isnull=False
        ).order_by('-cdate')
    }
    return render(request, template_name, data)


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'product_manager'])
def update_campaign_status(request):
    campaign_id = request.POST.get('campaign_id')
    new_status = request.POST.get('status')
    campaign = CollectionHiSeasonCampaign.objects.get(pk=campaign_id)
    campaign.update_safely(campaign_status=new_status)
    return JsonResponse({'status': 'success'})


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'product_manager'])
def campaign_form(request):
    if request.method == 'POST':
        campaign_id = request.GET.get('campaign_id', None)
        is_update = True if campaign_id else False

        json_data = json.loads(request.body)

        start_dpd = json_data['start_dpd']
        end_dpd = json_data['end_dpd']
        payment_terms_criteria = json_data['payment_terms_criteria']
        save_type = json_data['save_type']

        if end_dpd:
            payment_terms = payment_terms_criteria + ' dpd ' + start_dpd + ' and ' + end_dpd
        else:
            payment_terms = payment_terms_criteria + ' dpd ' + start_dpd

        eligible_partner_ids_string = json_data['eligible_partner_ids']
        eligible_partner_ids = list()
        if eligible_partner_ids_string:
            partners_ids = eligible_partner_ids_string.replace(" ", "").split(",")
            for partner_id in partners_ids:
                if partner_id.strip():
                    eligible_partner_ids.append(partner_id.strip())
        campaign_status = CampaignStatus.ACTIVE
        if save_type == CampaignStatus.DRAFT:
            campaign_status = CampaignStatus.DRAFT

        campaign_data = {
            'campaign_name': json_data['campaign_name'],
            'campaign_start_period': json_data['campaign_start_period'],
            'campaign_end_period': json_data['campaign_end_period'],
            'due_date_start': json_data['due_date_start'],
            'due_date_end': json_data['due_date_end'],
            'payment_terms': payment_terms,
            'eligible_partner_ids': eligible_partner_ids,
            'prize': json_data['prize'],
            'exclude_pending_refinancing': json_data['exclude_pending_refinancing'],
            'campaign_status': campaign_status,
            'announcement_date': json_data['announcement_date'],
        }
        with transaction.atomic():
            campaign, _ = CollectionHiSeasonCampaign.objects.update_or_create(
                pk=campaign_id, defaults=campaign_data
            )
            _save_inapp_settings(campaign, json_data['in_app_banners'], is_update)
            _save_onclick_banner(campaign, json_data['on_click_banner'], is_update)
            _save_comms_settings(campaign, json_data['campaign_comms'], is_update)

        return JsonResponse({'status': 'success', 'data': {'campaign_id': campaign.id}})

    elif request.method == 'GET':
        data = {}
        campaign_id = request.GET.get('campaign_id', None)

        if campaign_id:
            campaign = get_object_or_404(CollectionHiSeasonCampaign, pk=campaign_id)

            data['campaign_name'] = campaign.campaign_name
            data['campaign_start_period'] = format_date(
                campaign.campaign_start_period, 'dd MMM yyyy', locale='id_ID'
            )
            data['campaign_end_period'] = format_date(
                campaign.campaign_end_period, 'dd MMM yyyy', locale='id_ID'
            )
            data['due_date_start'] = format_date(
                campaign.due_date_start, 'dd MMM yyyy', locale='id_ID'
            )
            data['due_date_end'] = format_date(campaign.due_date_end, 'dd MMM yyyy', locale='id_ID')
            data['start_dpd'], data['end_dpd'] = get_dpd_from_payment_terms(campaign.payment_terms)

            data['eligible_partner_ids'] = ''
            if campaign.eligible_partner_ids:
                data['eligible_partner_ids'] = ",".join(campaign.eligible_partner_ids)

            data['exclude_pending_refinancing'] = campaign.exclude_pending_refinancing
            data['prize'] = campaign.prize
            data['announcement_date'] = format_date(
                campaign.announcement_date, 'dd MMM yyyy', locale='id_ID'
            )
            data['list_app_banner_and_schedule'] = list(
                CollectionHiSeasonCampaignBanner.objects.filter(  # noqa: E501
                    collection_hi_season_campaign=campaign, type=CampaignBanner.INAPP
                ).values(
                    'id',
                    'due_date',
                    'banner_start_date',
                    'banner_end_date',
                    'banner_content',
                    'banner_url',
                )
            )  # noqa: E501

            data['list_pn'], data['list_email'] = _get_campaign_comms(request, campaign)

        return render(request, 'collection_hi_season/campaign_form.html', data)


def _save_onclick_banner(campaign, banner_data, is_update=False):
    today = timezone.localtime(timezone.now())

    if 'blog_url' not in banner_data:
        banner_data['blog_url'] = None

    save_data = {
        'collection_hi_season_campaign_id': campaign.id,
        'type': 'onclick_banner',
        'banner_url': banner_data['banner_url'],
        'banner_content': banner_data['banner_content'],
        'blog_url': banner_data['blog_url'],
    }

    if is_update:
        save_data = {**save_data, 'udate': today}
        CollectionHiSeasonCampaignBanner.objects.filter(
            collection_hi_season_campaign_id=campaign.id, type=CampaignBanner.ON_CLICK
        ).update(**save_data)

    else:
        save_data = {**save_data, 'cdate': today, 'udate': today}
        CollectionHiSeasonCampaignBanner.objects.create(**save_data)


def _save_inapp_settings(campaign, banners_data, is_update=False):
    today = timezone.localtime(timezone.now())
    campaign_banners = []
    for banner in banners_data:
        save_data = {
            'collection_hi_season_campaign_id': campaign.id,
            'type': CampaignBanner.INAPP,
            'due_date': banner['due_date'],
            'banner_start_date': banner['start_showing_on'],
            'banner_end_date': banner['removed_on'],
            'banner_url': banner['banner_url'],
            'banner_content': banner['banner_content'],
        }

        if is_update:
            save_data = {**save_data, 'udate': today}
            CollectionHiSeasonCampaignBanner.objects.filter(id=banner['id']).update(**save_data)
        else:
            save_data = {**save_data, 'cdate': today, 'udate': today}
            campaign_banner = CollectionHiSeasonCampaignBanner(**save_data)
            campaign_banners.append(campaign_banner)

    if campaign_banners:
        CollectionHiSeasonCampaignBanner.objects.bulk_create(campaign_banners)


def _save_comms_settings(campaign, campaign_comms, is_update=False):
    today = timezone.localtime(timezone.now())

    for comm_data in campaign_comms:
        comm_setting_data = {
            'collection_hi_season_campaign_id': campaign.id,
            'type': comm_data['type'],
            'sent_at_dpd': comm_data['sent_at_dpd'],
            'template_code': comm_data['template_code'],
            'sent_time': comm_data['sent_time'],
            'email_subject': comm_data['email_subject'],
            'email_content': comm_data['email_content'],
            'pn_title': comm_data['pn_title'],
            'pn_body': comm_data['pn_body'],
            'block_url': None,
        }

        comm_setting_id = comm_data['comm_settings_id'] if is_update else None
        comm_setting, _ = CollectionHiSeasonCampaignCommsSetting.objects.update_or_create(
            pk=comm_setting_id, defaults=comm_setting_data
        )
        banner_type = '{}_banner'.format(comm_data['type'].lower())

        campaign_banners = []
        for banner in comm_data['banners']:
            save_data = {
                'collection_hi_season_campaign_id': campaign.id,
                'collection_hi_season_campaign_comms_setting_id': comm_setting.id,
                'type': banner_type,
                'due_date': banner['due_date'],
                'banner_start_date': banner['sent_on'],
                'banner_url': banner['banner_url'],
            }

            if is_update:
                save_data = {**save_data, 'udate': today}
                CollectionHiSeasonCampaignBanner.objects.filter(id=banner['id']).update(**save_data)
            else:
                save_data = {**save_data, 'cdate': today, 'udate': today}
                campaign_banner = CollectionHiSeasonCampaignBanner(**save_data)
                campaign_banners.append(campaign_banner)

        if campaign_banners and not is_update:
            CollectionHiSeasonCampaignBanner.objects.bulk_create(campaign_banners)


def _get_campaign_comms(request, campaign):
    pn_list, email_list = [], []
    campaign_comms = CollectionHiSeasonCampaignCommsSetting.objects.filter(
        collection_hi_season_campaign=campaign
    )

    for comm_settings in campaign_comms:
        campaign_banner = CollectionHiSeasonCampaignBanner.objects.filter(
            collection_hi_season_campaign_comms_setting=comm_settings,
            collection_hi_season_campaign=campaign,
        )

        banner_schedule = []
        if campaign_banner:
            banner_schedule = list(
                campaign_banner.values(
                    'id', 'due_date', 'banner_start_date', 'banner_content', 'banner_url'
                )
            )

        if comm_settings.type == CampaignCommunicationPlatform.PN:
            pn_setting_dict = {
                'comm_settings_id': comm_settings.id,
                'type': CampaignCommunicationPlatform.PN,
                'template_code': comm_settings.template_code,
                'sent_at_dpd': comm_settings.sent_at_dpd,
                'title': comm_settings.pn_title,
                'body': comm_settings.pn_body,
                'pn_banner_schedule': banner_schedule,
            }
            pn_list.append(pn_setting_dict)

        elif comm_settings.type == CampaignCommunicationPlatform.EMAIL:
            email_setting_dict = {
                'comm_settings_id': comm_settings.id,
                'type': CampaignCommunicationPlatform.EMAIL,
                'template_code': comm_settings.template_code,
                'sent_at_dpd': comm_settings.sent_at_dpd,
                'subject': comm_settings.email_subject,
                'block_url': comm_settings.block_url,
                'email_content': comm_settings.email_content,
                'email_banner_schedule': banner_schedule,
            }
            email_list.append(email_setting_dict)

    return pn_list, email_list


def ajax_upload_banner_hi_season(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if 'banner_image' not in request.FILES:
        return JsonResponse({'data': None})

    banner_image = request.FILES['banner_image']

    _, file_extension = os.path.splitext(banner_image.name)

    if file_extension not in ['.jpg', '.png', '.jpeg', '.webp']:
        return JsonResponse({"data": "Unsupport image type. Please upload jpeg, png or jpeg"})

    today = timezone.localtime(timezone.now())
    remote_path = 'collection-hi-season/{}{}/banner_{}'.format(
        today.year, today.month, banner_image.name
    )

    image = Image()
    image.image_source = -1
    image.image_type = 'hi_season_banner'
    image.url = remote_path
    image.save()

    file = functions.upload_handle_media(banner_image, "hi-season-banner/image")

    if file:
        upload_file_to_oss(settings.OSS_CAMPAIGN_BUCKET, file['file_name'], remote_path)
    return JsonResponse({'data': {'image_url': remote_path, 'image_id': image.id}})


def ajax_generate_comms_setting_schedule_hi_season(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = json.loads(request.body)
    due_date_start = datetime.strptime(data['due_date_start'], '%Y-%m-%d')
    due_date_end = datetime.strptime(data['due_date_end'], '%Y-%m-%d')
    sent_at_dpd = int(data['sent_at_dpd'])

    date_range = (due_date_end - due_date_start).days
    if date_range < 1:
        return JsonResponse({'data': {'list_comms_setting_schedule': []}})

    list_comms_setting_schedule = []
    for days in range(date_range + 1):
        due_date = due_date_start + timedelta(days=days)
        list_comms_setting_schedule.append(
            {'due_date': due_date, 'sent_on': due_date + timedelta(days=sent_at_dpd)}
        )

    return JsonResponse({'data': {'list_comms_setting_schedule': list_comms_setting_schedule}})


def ajax_generate_banner_schedule_hi_season(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = json.loads(request.body)
    campaign_start_period = data['campaign_start_period']
    due_date_start = datetime.strptime(data['due_date_start'], '%Y-%m-%d')
    due_date_end = datetime.strptime(data['due_date_end'], '%Y-%m-%d')
    start_dpd = data['start_dpd']
    diff_due_date_days = (due_date_end - due_date_start).days
    list_app_banner_and_schedule = []

    if diff_due_date_days < 1:
        return JsonResponse(
            {'data': {'list_app_banner_and_schedule': list_app_banner_and_schedule}}
        )

    for i in range(0, diff_due_date_days + 1):
        due_date = due_date_start + timedelta(days=i)
        list_app_banner_and_schedule.append(
            {
                'due_date': due_date,
                'start_showing_on': campaign_start_period,
                'removed_on': due_date + timedelta(days=(int(start_dpd) + 1)),
            }
        )

    return JsonResponse({'data': {'list_app_banner_and_schedule': list_app_banner_and_schedule}})


def ajax_get_partner_list_hi_season(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    partner_name = request.GET.get('partner_name', None)
    queryset = Partner.objects.all()
    if partner_name:
        queryset = queryset.filter(name__icontains=partner_name)

    partners_serialized = PartnerSerializer(queryset, many=True)
    partners_data = partners_serialized.data
    partners_data.append({'id': None, 'name': 'Julo One', 'company_name': 'Julo'})

    return JsonResponse({'partners': partners_data})


def ajax_delete_comms_setting(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    comm_setting_id = request.POST.get('comm_setting_id', None)
    comm_setting = get_object_or_404(CollectionHiSeasonCampaignCommsSetting, pk=comm_setting_id)

    CollectionHiSeasonCampaignBanner.objects.filter(
        collection_hi_season_comm_setting=comm_setting_id
    ).delete()
    comm_setting.delete()

    return JsonResponse({'status': 'success'})


class CreateInfoCardForHiSeason(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        # TODO : need to check with FE what required parameter here
        # data = request.POST.dict()

        info_card_property = InfoCardProperty.objects.create(
            title='', card_type='', card_action='', card_order_number=1
        )

        if 'image' in request.FILES:
            image_source_id = (info_card_property.id,)
            image_type = (CampaignCardProperty.BANNER_IMAGE,)
            image_file = request.FILES['image']

            _, file_extension = os.path.splitext(image_file.name)

            image_name = image_type
            remote_path = 'collection-hi-season/{}_{}{}'.format(
                image_name, image_source_id, file_extension
            )
            image = Image()
            image.image_source = image_source_id
            image.image_type = image_type
            image.url = remote_path
            image.save()

            file = functions.upload_handle_media(image_file, "collection-hi-season")

            upload_file_to_oss(settings.OSS_CAMPAIGN_BUCKET, file['file_name'], remote_path)

            return success_response()

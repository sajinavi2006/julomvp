import logging
import json
from object import julo_login_required, julo_login_required_group

from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.db import (transaction,
                       IntegrityError)

from juloserver.minisquad.models import (CollectionSquad,
                                         CollectionSquadAssignment)
from juloserver.julo.models import Agent
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.julo.clients import get_julo_sentry_client


logger = logging.getLogger(__name__)


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_SUPERVISOR)
def agent_properties(request):
    template = 'object/mini_squad/agent_properties.html'

    return render(
        request,
        template
    )


@csrf_protect
def ajax_get_bucket_and_agent_data(request):
    list_agents = User.objects.filter(
        is_active=True,
        groups__name__in=[
            JuloUserRoles.COLLECTION_BUCKET_2,
            JuloUserRoles.COLLECTION_BUCKET_3,
            JuloUserRoles.COLLECTION_BUCKET_4,
        ])\
        .values_list('username', flat=True)
    list_assigned_agents = CollectionSquadAssignment.objects.filter(
        agent__is_active=True, bucket_name__isnull=False)\
        .values('agent__username', 'bucket_name')

    list_squads = CollectionSquad.objects.all().values_list('squad_name', flat=True)
    bucket_types = [
        {
            'value': JuloUserRoles.COLLECTION_BUCKET_2,
            'name': 'Bucket 2'
        },
        {
            'value': JuloUserRoles.COLLECTION_BUCKET_3,
            'name': 'Bucket 3'
        },
        {
            'value': JuloUserRoles.COLLECTION_BUCKET_4,
            'name': 'Bucket 4'
        }]

    list_squads = {
        JuloUserRoles.COLLECTION_BUCKET_2:
            list(CollectionSquad.objects
                .filter(group__name=JuloUserRoles.COLLECTION_BUCKET_2)
                .values_list('squad_name', flat=True)),
        JuloUserRoles.COLLECTION_BUCKET_3:
            list(CollectionSquad.objects
                .filter(group__name=JuloUserRoles.COLLECTION_BUCKET_3)
                .values_list('squad_name', flat=True)),
        JuloUserRoles.COLLECTION_BUCKET_4:
            list(CollectionSquad.objects
                .filter(group__name=JuloUserRoles.COLLECTION_BUCKET_4)
                .values_list('squad_name', flat=True)),
    }

    return JsonResponse({
        'status': 'success',
        'list_agents': list(list_agents),
        'list_assigned_agents': list(list_assigned_agents),
        'bucket_types': bucket_types,
        'list_squads': list_squads
    }, safe=False)


@csrf_protect
def ajax_assign_agent_to_squad(request):
    data = request.POST.dict()
    agent = Agent.objects.get(user__username=data['agent'])
    sentry_client = get_julo_sentry_client()
    user = request.user

    try:
        with transaction.atomic():
            CollectionSquadAssignment.objects.create(agent=agent.user,
                                                     username=user.username,
                                                     bucket_name=data['bucket_name'])
        return JsonResponse({
            'status': 'success',
            'messages': 'success assign agent to new squad'
        })

    except IntegrityError:
        sentry_client.captureException()
        logger.info({
            'method': 'ajax_assign_agent_to_squad',
            'error': 'failed to update agent to other squad',
            'reason': 'db error',
            'agent': request.user.id
        })
        return JsonResponse({
            'status': 'failed',
            'messages': 'failed assign agent to new bucket'
        })

import logging
from typing import List

from celery import task
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    EmailHistory,
    FeatureSetting,
)
from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.utils import generate_agent_password


logger = logging.getLogger(__name__)


@task(queue='application_low')
def send_email_agent_password_regenerated(username, password, email_to):
    client = get_julo_email_client()
    subject = 'Credentials for Freelance "%s" now refreshed' % username
    msg = 'username: %s<br>password: %s<br>' % (username, password)
    status, body, headers = client.send_email(subject, msg, email_to)

    logger.info({
        'action': 'send_email_agent_password_regenerated',
        'username': username,
        'password': 'xxxxxxxxxxxxxxxx%s' % password[-5:],
        'email': email_to
    })

    message_id = headers['X-Message-Id']
    EmailHistory.objects.create(
        sg_message_id=message_id,
        to_email=email_to,
        subject=subject,
        message_content=msg
    )


@task(queue='application_low')
def scheduled_regenerate_freelance_agent_password():
    """
    Processes sending email with freelance agents' password.
    """
    freelance_users_ids = User.objects.filter(groups__name='freelance').values_list('pk', flat=True)
    send_password_email_for_collection.delay(freelance_users_ids)
    send_password_email_for_operation.delay(freelance_users_ids)


@task(queue='application_low')
def send_password_email_for_collection(freelance_user_ids: List[int]):
    """
    Sending email containing password to collection group freelance agents and the designated
    collection group leads.

    Args:
        freelance_user_ids (list): A list of integers containing ID/Primary Key of users with
            freelance group.
    """
    collection_agents = User.objects.filter(
        pk__in=freelance_user_ids,
        groups__name='collection',
        is_active=True,
        agent__isnull=False,
        email__isnull=False,
    ).exclude(email__exact='').order_by('username')

    subject = 'Credentials for Collection Freelance after %s' % timezone.now().date().strftime(
        "%d/%m/%Y")
    collection_lead_recipients = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.RECIPIENTS_BACKUP_PASSWORD
    ).parameters['collection']

    email_client = get_julo_email_client()
    backup_email_content = ''
    with (transaction.atomic()):
        for agent in collection_agents:
            password = generate_agent_password()
            agent.set_password(password)
            agent.save()
            content = 'username: %s password: %s<br>' % (agent.username, password)
            status, body, headers = email_client.send_email(subject, content, agent.email)
            backup_email_content += content

            EmailHistory.objects.create(
                sg_message_id=headers['X-Message-Id'],
                to_email=agent.email,
                subject='Collection Freelance Credential for {}'.format(agent.username)
            )

            logger.info({
                'action': 'send_password_email_for_collection',
                'message': 'Successfully send password to agent.',
                'agent_username': agent.username,
                'sendgrid_message_id': headers['X-Message-Id']
            })

    with transaction.atomic():
        for collection_lead_email in collection_lead_recipients:
            status, body, headers = email_client.send_email(subject, backup_email_content,
                collection_lead_email)

            EmailHistory.objects.create(
                sg_message_id=headers['X-Message-Id'],
                to_email=collection_lead_email,
                subject=subject,
            )

            logger.info({
                'action': 'send_password_email_for_collection',
                'message': 'Successfully send password to collection lead.',
                'recipients': collection_lead_email,
                'sendgrid_message_id': headers['X-Message-Id']
            })

    logger.info({
        'action': 'send_password_email_for_collection',
        'message': 'Successfully send password to collection group emails.',
    })


@task(queue='application_low')
def send_password_email_for_operation(freelance_user_ids: List[int]):
    """
    Sending email containing password to operation group freelance agents and the designated
    operation group leads.

    Args:
        freelance_user_ids (list): A list of integers containing ID/Primary Key of users with
            freelance group.
    """
    operation_agents = User.objects.filter(
        pk__in=freelance_user_ids,
        groups__name='operation',
        is_active=True,
        agent__isnull=False,
        email__isnull=False,
    ).exclude(email__exact='').order_by('username')

    subject = 'Credentials for Operation Freelance after %s' % timezone.now().date().strftime(
        "%d/%m/%Y")
    operation_lead_recipients = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.RECIPIENTS_BACKUP_PASSWORD
    ).parameters['operation']

    email_client = get_julo_email_client()
    backup_email_content = ''
    with transaction.atomic():
        for agent in operation_agents:
            password = generate_agent_password()
            agent.set_password(password)
            agent.save()
            content = 'username: %s password: %s<br>' % (agent.username, password)
            status, body, headers = email_client.send_email(subject, content, agent.email)
            backup_email_content += content

            EmailHistory.objects.create(
                sg_message_id=headers['X-Message-Id'],
                to_email=agent.email,
                subject='Operation Freelance Credential for {}'.format(agent.username)
            )

            logger.info({
                'action': 'send_password_email_for_operation',
                'message': 'Successfully send password to agent.',
                'agent_username': agent.username,
                'sendgrid_message_id': headers['X-Message-Id']
            })

    with transaction.atomic():
        for operation_lead_email in operation_lead_recipients:
            status, body, headers = email_client.send_email(subject, backup_email_content,
                operation_lead_email)

            EmailHistory.objects.create(
                sg_message_id=headers['X-Message-Id'],
                to_email=operation_lead_email,
                subject=subject,
            )

            logger.info({
                'action': 'send_password_email_for_operation',
                'message': 'Successfully send password to collection lead.',
                'recipients': operation_lead_email,
                'sendgrid_message_id': headers['X-Message-Id']
            })

    logger.info({
        'action': 'send_password_email_for_operation',
        'message': 'Successfully send password to operation group emails.',
    })

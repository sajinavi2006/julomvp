from __future__ import unicode_literals

from django.contrib.auth.models import Group
from django.db import migrations, models
from django.conf import settings
import django.db.models.deletion

from juloserver.julo.models import Loan


def update_role_collection_agent(apps, schema_editor):
    freelance_group = Group.objects.filter(name='collection_freelance').last()
    agent_group = Group.objects.filter(name='collection_agent').last()
    agent_90dpd_group = Group.objects.filter(name='collection_agent_90dpd').last()

    if freelance_group:
        freelance_group.name = 'collection_agent_1'
        freelance_group.save()
    if agent_group:
        agent_group.name = 'collection_agent_2'
        agent_group.save()
    if agent_90dpd_group:
        agent_90dpd_group.name = 'collection_agent_3'
        agent_90dpd_group.save()

from juloserver.julo.models import Loan


def migrate_agent_to_agent_2(apps, schema_editor):
    
    loans = Loan.objects.filter(agent__isnull=False)
    for loan in loans:
        loan.agent_2 = loan.agent
        loan.save()
    
class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_role_collection_agent, migrations.RunPython.noop),
        migrations.RunPython(migrate_agent_to_agent_2, migrations.RunPython.noop),
    ]

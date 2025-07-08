from __future__ import unicode_literals

from django.contrib.auth.models import Group
from django.db import migrations, models
from django.conf import settings
import django.db.models.deletion

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

def migrate_agent_to_agent_2(apps, schema_editor):
    Loan = apps.get_model("julo", "Loan")
    loans = Loan.objects.filter(agent__isnull=False)
    for loan in loans:
        loan.agent_2 = loan.agent
        loan.save()
    
class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('julo', '0287_auto_20180913_1055'),
    ]

    operations = [
        migrations.RunPython(update_role_collection_agent, migrations.RunPython.noop),
        migrations.AddField(
            model_name='loan',
            name='agent_2',
            field=models.ForeignKey(blank=True, db_column='agent_2', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='agent_2', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='loan',
            name='agent_3',
            field=models.ForeignKey(blank=True, db_column='agent_3', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='agent_3', to=settings.AUTH_USER_MODEL),
        ),
        migrations.RunPython(migrate_agent_to_agent_2, migrations.RunPython.noop),
    ]

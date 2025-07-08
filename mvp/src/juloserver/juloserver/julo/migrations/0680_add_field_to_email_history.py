from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0679_alter_loan_description_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='EmailHistory',
            name='error_message',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='EmailHistory',
            name='status',
            field=models.CharField(max_length=20, default='Pending'),
        ),
        migrations.AlterField(
            model_name='EmailHistory',
            name='sg_message_id',
            field=models.CharField(max_length=150, blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='EmailHistory',
            name='subject',
            field=models.CharField(max_length=250, blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='EmailHistory',
            name='message_content',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='EmailHistory',
            name='to_email',
            field=models.EmailField(max_length=250, null=True, blank=True)
        ),
    ]

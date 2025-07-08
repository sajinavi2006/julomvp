from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0134_add_ptp_date_payment'),
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='hrd_name',
            field=models.CharField(max_length=100, blank=True, null=True,validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.AddField(
            model_name='application',
            name='company_address',
            field=models.CharField(max_length=100, blank=True, null=True,validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.AddField(
            model_name='application',
            name='number_of_employees',
            field=models.IntegerField(blank=True, null=True)
        ),
        migrations.AddField(
            model_name='application',
            name='position_employees',
            field=models.CharField(max_length=100, blank=True, null=True,validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.AddField(
            model_name='application',
            name='employment_status',
            field=models.CharField(max_length=100, blank=True, null=True,validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.AddField(
            model_name='application',
            name='billing_office',
            field=models.CharField(max_length=100, blank=True, null=True,validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.AddField(
            model_name='application',
            name='mutation',
            field=models.CharField(max_length=100, blank=True, null=True,validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.AddField(
            model_name='applicationoriginal',
            name='hrd_name',
            field=models.CharField(max_length=100, blank=True, null=True,validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.AddField(
            model_name='applicationoriginal',
            name='company_address',
            field=models.CharField(max_length=100, blank=True, null=True,validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.AddField(
            model_name='applicationoriginal',
            name='number_of_employees',
            field=models.IntegerField(blank=True, null=True)
        ),
        migrations.AddField(
            model_name='applicationoriginal',
            name='position_employees',
            field=models.CharField(max_length=100, blank=True, null=True,validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.AddField(
            model_name='applicationoriginal',
            name='employment_status',
            field=models.CharField(max_length=100, blank=True, null=True,validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.AddField(
            model_name='applicationoriginal',
            name='billing_office',
            field=models.CharField(max_length=100, blank=True, null=True,validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.AddField(
            model_name='applicationoriginal',
            name='mutation',
            field=models.CharField(max_length=100, blank=True, null=True,validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
    ]

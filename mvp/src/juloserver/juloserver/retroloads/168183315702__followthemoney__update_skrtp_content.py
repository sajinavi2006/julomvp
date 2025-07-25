# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-04-18 15:52
from __future__ import unicode_literals

from django.db import migrations
from juloserver.followthemoney.services import update_loan_agreement_template

def update_skrtp_default_template(apps, _schema_editor):
    update_loan_agreement_template('/juloserver/julo/templates/loan_agreement/julo_one_skrtp.html')


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_skrtp_default_template, migrations.RunPython.noop)
    ]

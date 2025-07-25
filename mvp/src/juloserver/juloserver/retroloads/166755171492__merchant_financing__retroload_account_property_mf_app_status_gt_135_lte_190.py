# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-11-04 08:48
from __future__ import unicode_literals

from collections import defaultdict

from django.db import migrations
from django.db import transaction
from juloserver.account.models import (
    AccountLimit, AccountProperty, AccountPropertyHistory
)
from juloserver.apiv2.models import AutoDataCheck
from juloserver.account.services.credit_limit import (
    get_is_proven,
    get_proven_threshold,
    get_voice_recording,
)
from juloserver.julo.models import Application, JobType
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes


def backfill_account_property_mf(apps, schema_editor):
    with transaction.atomic():
        applications = Application.objects.filter(
            product_line__product_line_code=ProductLineCodes.MF,
            application_status__gt=ApplicationStatusCodes.APPLICATION_DENIED,
            application_status__lte=ApplicationStatusCodes.LOC_APPROVED
        ).order_by('account_id').select_related('product_line') \
            .values('account_id', 'job_type', 'id')

        account_id_dicts = defaultdict(int)
        application_job_dicts = defaultdict(str)
        job_types_list = set()
        application_ids = set()
        for application in applications.iterator():
            account_id = application.get('account_id', None)
            if account_id:
                account_id_dicts[application['account_id']] = application['id']
                application_job_dicts[application['account_id']] = application['job_type']
                job_types_list.add(application['job_type'])
                application_ids.add(application['id'])

        # mapping job types
        job_types_dict = defaultdict(str)
        job_types = JobType.objects.filter(job_type__in=job_types_list)
        for job in job_types.iterator():
            job_types_dict[job.job_type] = job.is_salaried

        # mapping auto data check
        data_checks_dict = defaultdict(int)
        data_checks = AutoDataCheck.objects.filter(
            application_id__in=application_ids, data_to_check='inside_premium_area').order_by('id')

        for data_check in data_checks.iterator():
            data_checks_dict[data_check.application_id] = data_check.is_okay

        account_have_properties_ids = AccountProperty.objects.filter(
            account_id__in=account_id_dicts.keys()).values_list('account_id', flat=True)

        # mapping account doesn't have account property
        account_not_have_properties = []
        for account_id, _ in account_id_dicts.items():
            if account_id not in account_have_properties_ids:
                account_not_have_properties.append(account_id)

        # mapping account limit
        account_credit_limit_dict = defaultdict(int)
        account_limits = AccountLimit.objects.filter(account_id__in=account_not_have_properties)
        for account_limit in account_limits.iterator():
            account_credit_limit_dict[account_limit.account_id] = account_limit.set_limit

        # create account properties
        account_properties = []
        for acc_id in account_not_have_properties:
            try:
                is_salaried = application_job_dicts[acc_id]
                if not is_salaried:
                    is_salaried = False
            except (AttributeError, KeyError):
                is_salaried = False

            try:
                application_id = account_id_dicts[acc_id]
                is_premium_area = data_checks_dict[application_id]
                if not is_premium_area:
                    is_premium_area = False
            except (AttributeError, KeyError):
                is_premium_area = False

            set_limit = account_credit_limit_dict[acc_id]
            is_proven = get_is_proven()
            account_property = AccountProperty(
                is_proven=is_proven,
                account_id=acc_id,
                pgood=0.0,
                p0=0.0,
                is_salaried=is_salaried,
                is_premium_area=is_premium_area,
                proven_threshold=get_proven_threshold(set_limit),
                voice_recording=get_voice_recording(is_proven),
                concurrency=True,
            )
            account_properties.append(account_property)

        AccountProperty.objects.bulk_create(account_properties, batch_size=30)

        # Create account property history
        list_account_property = AccountProperty.objects.filter(
            account_id__in=account_not_have_properties).order_by('id')
        acc_property_histroy_bulk_create = []
        for acc_property in list_account_property.iterator():
            account_property_dict = acc_property.__dict__
            for key, value in account_property_dict.items():
                exclude_key = {"cdate", "udate", "_state", "id", "account_id",
                                "last_graduation_date", "is_entry_level",
                                "refinancing_ongoing", "ever_refinanced"}
                if key in exclude_key:
                    continue

                acc_property_history = AccountPropertyHistory(
                    account_property=acc_property,
                    field_name=key,
                    value_old=None,
                    value_new=value
                )
                acc_property_histroy_bulk_create.append(acc_property_history)

        AccountPropertyHistory.objects.bulk_create(acc_property_histroy_bulk_create,
                                                   batch_size=30)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(backfill_account_property_mf, migrations.RunPython.noop)
    ]

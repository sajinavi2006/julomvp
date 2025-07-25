# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-06-07 08:00
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='MonnaiEmailBasicInsight',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'monnai_email_basic_insight_id',
                    juloserver.julocore.customized_psycopg2.models.BigAutoField(
                        db_column='monnai_email_basic_insight_id', primary_key=True, serialize=False
                    ),
                ),
                ('deliverable', models.NullBooleanField()),
                ('domain_name', models.CharField(blank=True, max_length=255, null=True)),
                ('tld', models.CharField(blank=True, max_length=10, null=True)),
                ('creation_time', models.DateTimeField(blank=True, null=True)),
                ('update_time', models.DateTimeField(blank=True, null=True)),
                ('expiry_time', models.DateTimeField(blank=True, null=True)),
                ('registered', models.NullBooleanField()),
                ('company_name', models.CharField(blank=True, max_length=255, null=True)),
                ('registrar_name', models.CharField(blank=True, max_length=255, null=True)),
                ('disposable', models.NullBooleanField()),
                ('free_provider', models.NullBooleanField()),
                ('dmarc_compliance', models.NullBooleanField()),
                ('spf_strict', models.NullBooleanField()),
                ('suspicious_tld', models.NullBooleanField()),
                ('website_exists', models.NullBooleanField()),
                ('accept_all', models.NullBooleanField()),
                ('custom', models.NullBooleanField()),
                ('is_breached', models.NullBooleanField()),
                (
                    'breaches',
                    django.contrib.postgres.fields.jsonb.JSONField(
                        blank=True, null=True, verbose_name='Breach Details'
                    ),
                ),
                ('no_of_breaches', models.IntegerField(blank=True, null=True)),
                ('first_breach', models.DateField(blank=True, null=True)),
                ('last_breach', models.DateField(blank=True, null=True)),
                ('raw_response', django.contrib.postgres.fields.jsonb.JSONField()),
                (
                    'application',
                    juloserver.julocore.customized_psycopg2.models.BigForeignKey(
                        db_column='application_id',
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to='julo.Application',
                    ),
                ),
                (
                    'monnai_insight_request',
                    juloserver.julocore.customized_psycopg2.models.BigOneToOneField(
                        db_column='monnai_insight_request_id',
                        db_constraint=False,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name='email_basic_insight',
                        to='fraud_score.MonnaiInsightRequest',
                    ),
                ),
            ],
            options={
                'db_table': 'monnai_email_basic_insight',
            },
        ),
        migrations.CreateModel(
            name='MonnaiEmailSocialInsight',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'monnai_email_social_insight_id',
                    juloserver.julocore.customized_psycopg2.models.BigAutoField(
                        primary_key=True, serialize=False
                    ),
                ),
                ('registered_profiles', models.PositiveIntegerField(blank=True, null=True)),
                (
                    'registered_consumer_electronics_profiles',
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    'registered_email_provider_profiles',
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    'registered_ecommerce_profiles',
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    'registered_social_media_profiles',
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    'registered_messaging_profiles',
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    'registered_professional_profiles',
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    'registered_entertainment_profiles',
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                ('registered_travel_profiles', models.PositiveIntegerField(blank=True, null=True)),
                ('age_on_social', models.FloatField(blank=True, null=True)),
                ('number_of_names_returned', models.PositiveIntegerField(blank=True, null=True)),
                ('number_of_photos_returned', models.PositiveIntegerField(blank=True, null=True)),
                ('facebook_registered', models.NullBooleanField()),
                ('instagram_registered', models.NullBooleanField()),
                ('twitter_registered', models.NullBooleanField()),
                ('quora_registered', models.NullBooleanField()),
                ('github_registered', models.NullBooleanField()),
                ('linkedin_registered', models.NullBooleanField()),
                ('linkedin_url', models.URLField(blank=True, null=True)),
                ('linkedin_name', models.CharField(blank=True, max_length=255, null=True)),
                ('linkedin_company', models.CharField(blank=True, max_length=255, null=True)),
                ('raw_response', django.contrib.postgres.fields.jsonb.JSONField()),
                (
                    'application',
                    juloserver.julocore.customized_psycopg2.models.BigForeignKey(
                        db_column='application_id',
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to='julo.Application',
                    ),
                ),
                (
                    'monnai_insight_request',
                    juloserver.julocore.customized_psycopg2.models.BigOneToOneField(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name='email_social_insight',
                        to='fraud_score.MonnaiInsightRequest',
                    ),
                ),
            ],
            options={
                'db_table': 'monnai_email_social_insight',
            },
        ),
        migrations.CreateModel(
            name='MonnaiPhoneBasicInsight',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'monnai_phone_basic_insight_id',
                    juloserver.julocore.customized_psycopg2.models.BigAutoField(
                        db_column='monnai_phone_basic_insight_id', primary_key=True, serialize=False
                    ),
                ),
                ('phone_disposable', models.NullBooleanField()),
                ('active', models.NullBooleanField()),
                ('activation_date', models.DateTimeField(blank=True, null=True)),
                ('active_since_x_days', models.PositiveIntegerField(blank=True, null=True)),
                ('sim_type', models.TextField(blank=True, null=True)),
                ('phone_number_age', models.PositiveIntegerField(blank=True, null=True)),
                ('phone_number_age_description', models.TextField(blank=True, null=True)),
                ('phone_tenure', models.PositiveIntegerField(blank=True, null=True)),
                ('last_deactivated', models.DateTimeField(blank=True, null=True)),
                ('is_spam', models.NullBooleanField()),
                (
                    'raw_response',
                    django.contrib.postgres.fields.jsonb.JSONField(blank=True, null=True),
                ),
                (
                    'application',
                    juloserver.julocore.customized_psycopg2.models.BigForeignKey(
                        db_column='application_id',
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to='julo.Application',
                    ),
                ),
                (
                    'monnai_insight_request',
                    juloserver.julocore.customized_psycopg2.models.BigOneToOneField(
                        db_column='monnai_insight_request_id',
                        db_constraint=False,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name='phone_basic_insight',
                        to='fraud_score.MonnaiInsightRequest',
                    ),
                ),
            ],
            options={
                'db_table': 'monnai_phone_basic_insight',
            },
        ),
        migrations.CreateModel(
            name='MonnaiPhoneSocialInsight',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'monnai_phone_social_insight_id',
                    juloserver.julocore.customized_psycopg2.models.BigAutoField(
                        db_column='monnai_phone_social_insight_id',
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('registered_profiles', models.PositiveIntegerField(blank=True, null=True)),
                (
                    'registered_email_provider_profiles',
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    'registered_ecommerce_profiles',
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    'registered_social_media_profiles',
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    'registered_professional_profiles',
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    'registered_messaging_profiles',
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                ('last_activity', models.DateTimeField(blank=True, null=True)),
                ('number_of_names_returned', models.IntegerField(blank=True, null=True)),
                ('number_of_photos_returned', models.IntegerField(blank=True, null=True)),
                ('messaging_telegram_registered', models.NullBooleanField()),
                ('messaging_whatsapp_registered', models.NullBooleanField()),
                ('messaging_viber_registered', models.NullBooleanField()),
                ('messaging_kakao_registered', models.NullBooleanField()),
                ('messaging_skype_registered', models.NullBooleanField()),
                ('messaging_ok_registered', models.NullBooleanField()),
                ('messaging_zalo_registered', models.NullBooleanField()),
                ('messaging_line_registered', models.NullBooleanField()),
                ('messaging_snapchat_registered', models.NullBooleanField()),
                ('email_provider_google_registered', models.NullBooleanField()),
                ('social_media_facebook_registered', models.NullBooleanField()),
                ('social_media_twitter_registered', models.NullBooleanField()),
                ('social_media_instagram_registered', models.NullBooleanField()),
                ('raw_response', django.contrib.postgres.fields.jsonb.JSONField()),
                (
                    'application',
                    juloserver.julocore.customized_psycopg2.models.BigForeignKey(
                        db_column='application_id',
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to='julo.Application',
                    ),
                ),
                (
                    'monnai_insight_request',
                    juloserver.julocore.customized_psycopg2.models.BigOneToOneField(
                        db_column='monnai_insight_request_id',
                        db_constraint=False,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name='phone_social_insight',
                        to='fraud_score.MonnaiInsightRequest',
                    ),
                ),
            ],
            options={
                'db_table': 'monnai_phone_social_insight',
            },
        ),
    ]

from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('webapp', '__first__'),
        ('loan_refinancing', '0036_retroload_recommendation_order'),
    ]

    operations = [
        migrations.CreateModel(
            name='CollectionOfferEligibility',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='collection_offer_eligibility_id', primary_key=True)),
                ('mobile_phone', models.CharField(max_length=50)),
                ('status', models.TextField(blank=True, null=True)),
                ('application', models.ForeignKey(blank=True,  null=True, db_column='application_id',
                                 on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Application')),
                ('loan', models.ForeignKey(blank=True,  null=True, db_column='loan_id',
                                 on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Loan')),
                ('web_scraped_data', models.ForeignKey(blank=True,  null=True, db_column='web_scraped_data_id',
                                 on_delete=django.db.models.deletion.DO_NOTHING, to='webapp.WebScrapedData')),
            ],
            options={
                'db_table': 'collection_offer_eligibility',
            },
        ),
        migrations.RunSQL(
            "ALTER TABLE collection_offer_eligibility ALTER COLUMN loan_id TYPE bigint;"
        ),
        migrations.RunSQL(
            "ALTER TABLE collection_offer_eligibility ALTER COLUMN application_id TYPE bigint;"
        )
    ]

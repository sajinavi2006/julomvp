from __future__ import unicode_literals

from builtins import str
from builtins import range
from django.db import migrations, models
from juloserver.julo.product_lines import ProductLineCodes, ProductLineManager
import django.db.models.deletion
from django.conf import settings
import random

def load_bri_product_lines(apps, schema_editor):
    for code in ProductLineCodes.bri():
        ProductLine = apps.get_model("julo", "ProductLine")
        pl = ProductLineManager.get_or_none(code)
        if pl is None:
            continue
        if ProductLine.objects.filter(product_line_code=code).first():
            continue
        ProductLine.objects.create(
            product_line_code=pl.product_line_code,
            product_line_type=pl.product_line_type,
            min_amount=pl.min_amount,
            max_amount=pl.max_amount,
            min_duration=pl.min_duration,
            max_duration=pl.max_duration,
            min_interest_rate=pl.min_interest_rate,
            max_interest_rate=pl.max_interest_rate,
            payment_frequency=pl.payment_frequency
        )
        
def load_new_mantri_code(apps, schema_editor):
    Mantri = apps.get_model("julo", "Mantri")
    list_data = random.sample(list(range(1111, 9999)), 5)
    for data in list_data:
        Mantri.objects.create(code="test"+str(data))
        
def load_new_lender(apps, schema_editor):
    Lender = apps.get_model("julo", "Lender")
    Lender.objects.create(phone_number='62828282828', email='bri@example.com', name='bri')
        
class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0147_paymentevent_payment_method'),
    ]

    operations = [
        migrations.CreateModel(
            name='Mantri',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='mantri_id', primary_key=True, serialize=False)),
                ('code', models.CharField(max_length=20, null=True)),
            ],
            options={
                'db_table': 'mantri',
            },
        ),
        migrations.AddField(
            model_name='application',
            name='mantri',
            field=models.ForeignKey(blank=True, db_column='mantri_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Mantri'),
        ),
        migrations.AddField(
            model_name='applicationoriginal',
            name='mantri',
            field=models.ForeignKey(blank=True, db_column='mantri_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Mantri'),
        ),
        migrations.CreateModel(
            name='BankIndonesiaCheck',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='bank_indonesia_check_id', primary_key=True, serialize=False)),
                ('request_id', models.CharField(max_length=50, null=True)),
                ('status', models.BooleanField(default=False)),
                ('result', models.CharField(max_length=50, null=True)),
                ('application', models.ForeignKey(db_column='application_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Application')),
            ],
            options={
                'db_table': 'bank_indonesia_check',
            },
        ),
        migrations.CreateModel(
            name='MockBri',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='mock_bri_id', primary_key=True, serialize=False)),
                ('application_id', models.CharField(max_length=20, null=True)),
                ('request_id', models.CharField(max_length=50, null=True)),
                ('status_bi', models.BooleanField(default=False)),
                ('loan_id', models.CharField(max_length=20, null=True)),
                ('nik', models.CharField(max_length=20, null=True)),
                ('account_number', models.IntegerField(blank=True, null=True)),
                ('status_account', models.BooleanField(default=False)),
                ('amount', models.BigIntegerField(blank=True, null=True)),
                ('request_loan_id', models.CharField(max_length=50, null=True)),
            ],
            options={
                'db_table': 'mock_bri',
            },
        ),
        migrations.CreateModel(
            name='Lender',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='lender_id', primary_key=True, serialize=False)),
                ('phone_number', models.CharField(blank=True, max_length=50, null=True, validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')])),
                ('email', models.EmailField(blank=True, max_length=254, null=True)),
                ('name', models.CharField(blank=True, max_length=100, null=True, validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')])),
                ('token', models.CharField(blank=True, max_length=256, null=True)),
                ('user', models.OneToOneField(db_column='auth_user_id', on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, null=True, blank=True)),
            ],
            options={
                'db_table': 'lender',
            },
        ),
        migrations.CreateModel(
            name='LoanAccountNumber',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='loan_account_number_id', primary_key=True, serialize=False)),
                ('request_id', models.CharField(max_length=40, null=True)),
                ('status_available', models.BooleanField(default=False)),
                ('availabe_date', models.DateTimeField(blank=True, null=True)),
                ('account_number', models.IntegerField(blank=True, null=True)),
                ('amount', models.BigIntegerField(blank=True, null=True)),
            ],
            options={
                'db_table': 'loan_account_number',
            },
        ),
        migrations.AddField(
            model_name='loan',
            name='loan_account_number',
            field=models.ForeignKey(blank=True, db_column='loan_account_number', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.LoanAccountNumber'),
        ),
        migrations.RunPython(load_bri_product_lines),
        migrations.RunPython(load_new_mantri_code),
        migrations.RunPython(load_new_lender),
    ]

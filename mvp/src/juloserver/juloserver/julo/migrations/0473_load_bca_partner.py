from __future__ import unicode_literals

from django.db import migrations, models
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from juloserver.api_token.models import ExpiryToken as Token
from ..partners import PartnerConstant


def load_bca_partner(apps, schema_editor):
    # User = apps.get_model("auth", "User")
    # Token = apps.get_model("authtoken", "Token")
    password = make_password('bca123')
    user = User.objects.create(username='bca', password=password, email='bca@example.com')
    token, created = Token.objects.get_or_create(user=user)

    Partner = apps.get_model("julo", "Partner")
    bca_partner = Partner.objects.create(user_id=user.id,
                                         name=PartnerConstant.BCA_PARTNER,
                                         email='bca@example.com',
                                         type='service',
                                         token=token.key)


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0472_insert_payback_transaction'),
    ]

    operations = [
        migrations.AlterField(
            model_name='partner',
            name='type',
            field=models.CharField(blank=True, choices=[('referrer', 'referrer'), ('receiver', 'receiver'), ('lender', 'lender'), ('service', 'service')], max_length=50, null=True),
        ),
        migrations.RunPython(load_bca_partner, migrations.RunPython.noop)
    ]

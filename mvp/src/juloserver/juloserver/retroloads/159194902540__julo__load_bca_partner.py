from __future__ import unicode_literals

from django.db import migrations, models
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from juloserver.api_token.models import ExpiryToken as Token

from juloserver.julo.partners import PartnerConstant


from juloserver.julo.models import Partner

from django.contrib.auth.models import User



def load_bca_partner(apps, schema_editor):
    # 
    # 
    password = make_password('bca123')
    user = User.objects.create(username='bca', password=password, email='bca@example.com')
    token, created = Token.objects.get_or_create(user=user)

    
    bca_partner = Partner.objects.create(user_id=user.id,
                                         name=PartnerConstant.BCA_PARTNER,
                                         email='bca@example.com',
                                         type='service',
                                         token=token.key)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(load_bca_partner, migrations.RunPython.noop)
    ]

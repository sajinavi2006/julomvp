# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


from juloserver.julo.models import FaqItem



def update_faq_text(apps, schema_editor):
    
    faq = FaqItem.objects.filter(
        question='Apakah pinjaman JULO Cicil itu?'
        ).first()
    
    faq.description = 'JULO Cicil adalah Pinjaman KTA berkisar antara Rp 1 - 8 juta, yang dapat dicicil selama 2 - 6 bulan. Bunga JULO Cicil berkisar antara 1.5% - 4% per bulan, ditetapkan berdasarkan hasil analisa kelayakan kredit masing - masing nasabah.<br><br> JULO Cicil juga memiliki program Cashback (dapat uang kembali) sebesar 2% saat Anda membayarkan cicilan sebelum atau tepat pada waktunya.'
    faq.save()


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_faq_text, migrations.RunPython.noop)
    ]
# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-03-30 10:05
from __future__ import unicode_literals
from juloserver.customer_module.services.digital_signature import DigitalSignature, \
    CertificateAuthority
from juloserver.followthemoney.models import LenderCurrent
from django.conf import settings

from django.db import migrations


def generate_certificate_for_grab_lenders(apps, schema_editor):
    lenders = LenderCurrent.objects.filter(lender_name__in={'ska', 'ska2'})
    new_email = "diah.eristianti@sentrakalitaabadi.id"
    for lender in lenders:
        user = lender.user
        if not user:
            return
        user.email = new_email
        user.save()
        signer = DigitalSignature.Signer(
            user=user,
            key_name=f"key-{user.id}-1",
            for_organization=True,
            organization="PT Sentral Kalita Abadi",
            full_name="Anthon Suryadi",
            email="",
            province="DKI Jakarta",
            city="Jakarta Selatan",
            address="Gedung Millennium Centennial Center, Jl. Jenderal Sudirman, Kuningan, Setiabudi, Jakarta Selatan",
        )
        if not signer.key_exists():
            signer.generate_key_pairs()
        if signer.signer.has_certificate():
            return
        signer.signer.generate_csr()
        CertificateAuthority(
            private_key=settings.JULO_CERTIFICATE_AUTHORITY["PRIVATE_KEY"],
            passphrase=settings.JULO_CERTIFICATE_AUTHORITY["PASSPHRASE"],
            certificate=settings.JULO_CERTIFICATE_AUTHORITY["CERTIFICATE"],
        ).make_certificate(signer.signer)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(generate_certificate_for_grab_lenders, migrations.RunPython.noop),
    ]

# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from juloserver.julo.partners import PartnerConstant
from juloserver.followthemoney.models import LenderCurrent, LenderBankAccount
from juloserver.followthemoney.constants import BankAccountType, BankAccountStatus

def retroload_lender_bank_account(apps, schema_editor):
    jtp_lender = LenderCurrent.objects.get_or_none(lender_name=PartnerConstant.JTP_PARTNER)
    if jtp_lender:
        jtp_lender.poc_name='Thadea Silvana'
        jtp_lender.poc_email='thadea@julofinance.com'
        jtp_lender.poc_phone='+628111111111'
        jtp_lender.lender_address='Office 88@Kasablanka Tower A, Jl. Casablanca No.Kav 88, RT.16/RW.5, Menteng Dalam, Tebet, South Jakarta City, Jakarta 12820'
        jtp_lender.business_type='perusahaan umum'
        jtp_lender.pks_number='1.JTF.201707'
        jtp_lender.service_fee=0.02  # confirmed by Yogi
        jtp_lender.source_of_fund='pinjaman'
        jtp_lender.addendum_number = 'AD001'
        jtp_lender.lender_status = 'active'
        jtp_lender.lender_display_name = 'PT Julo Teknologi Perdana'
        jtp_lender.poc_position =  'Commisioner'
        jtp_lender.save()


    lender_bank_account_data =[
        LenderBankAccount(lender=jtp_lender,
                          bank_account_type=BankAccountType().RDL,
                          bank_name="BANK SAHABAT SAMPOERNA",
                          account_name="PT Julo Teknologi Perdana",
                          account_number="1020199888",
                          bank_account_status=BankAccountStatus().ACTIVE),
        LenderBankAccount(lender=jtp_lender,
                          bank_account_type=BankAccountType().DEPOSIT_VA,
                          bank_name="BANK SAHABAT SAMPOERNA",
                          account_name="PT Julo Teknologi Perdana",
                          account_number="8280011020199888",
                          bank_account_status=BankAccountStatus().ACTIVE),
        LenderBankAccount(lender=jtp_lender,
                          bank_account_type=BankAccountType().DISBURSEMENT_VA,
                          bank_name="BANK SAHABAT SAMPOERNA",
                          account_name="PT Julo Teknologi Finansial",
                          account_number="6010011036888888",
                          bank_account_status=BankAccountStatus().ACTIVE),
        LenderBankAccount(lender=jtp_lender,
                          bank_account_type=BankAccountType().REPAYMENT_VA,
                          bank_name="BANK SAHABAT SAMPOERNA",
                          account_name="PT Julo Teknologi Perdana",
                          account_number="8280021020199888",
                          bank_account_status=BankAccountStatus().ACTIVE),
        LenderBankAccount(lender=jtp_lender,
                          bank_account_type=BankAccountType().WITHDRAWAL,
                          bank_name="BANK CENTRAL ASIA, Tbk (BCA)",
                          account_name="PT Julo Teknologi Perdana",
                          account_number="5425250016",
                          bank_account_status=BankAccountStatus().ACTIVE)
    ]
    LenderBankAccount.objects.bulk_create(lender_bank_account_data)

    other_lenders = LenderCurrent.objects.exclude(lender_name=PartnerConstant.JTP_PARTNER)
    for lender in other_lenders:
        lender.lender_status = 'inactive'
        lender.save()

class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(retroload_lender_bank_account)
    ]

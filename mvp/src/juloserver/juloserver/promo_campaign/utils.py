import logging

from functools import wraps

from juloserver.julo.models import (
    EmailHistory,
    SmsHistory)
from juloserver.julo.services2.sms import create_sms_history
from juloserver.julo.exceptions import JuloException
from juloserver.julo.constants import ProductLineCodes

from .constants import RamadanCampaign
logger = logging.getLogger(__name__)


def save_email_history(func):
    @wraps(func)
    def save_email_wrapper(*args, **kwargs):
        try:
            data = func(*args, **kwargs)
            EmailHistory.objects.create(
                customer=data['customer'],
                sg_message_id=data['headers']["X-Message-Id"],
                to_email=data['email'],
                subject=data['subject'],
                application=data['application'],
                message_content=data['msg'],
                template_code=data['template_code'],
                status=data['status']
            )

            return data
        except JuloException as e:
            logger.error({
                'method': 'save_email_history',
                'caller': func.__name__,
                'args': args,
                'kwargs': kwargs,
            })

            raise e

    return save_email_wrapper


def save_sms_history(func):
    @wraps(func)
    def save_sms_wrapper(*args, **kwargs):
        try:
            data = func(*args, **kwargs)
            create_sms_history(**data)

            return data
        except JuloException as e:
            logger.error({
                'method': 'save_email_history',
                'caller': func.__name__,
                'args': args,
                'kwargs': kwargs,
            })

            raise e

    return save_sms_wrapper


def get_email_template_from_dpd_and_product_code(dpd, product_code):
    money_wing = u'\U0001F4B8'
    astonished_face = u'\U0001F632'
    partner_subject_t7 = 'Bayar Cicilan Bisa Dapat Uang Tunai 5 Juta Rupiah?' + \
                         money_wing + astonished_face + 'Cari Tahu di Sini!'
    mtl_subject_t7 = 'Bayar Cicilan JULO 3 Hari Sebelum Jatuh Tempo'\
                     'dan Dapatkan Uang Tunai Jutaan Rupiah!' + money_wing
    mtl_subject_t3 = 'KESEMPATAN TERAKHIR' + astonished_face + \
                     'Uang Tunai Jutaan Rupiah Menunggu Anda, nih!' + money_wing
    partner_subject_t3 = 'KESEMPATAN TERAKHIR Menangkan Uang Tunai'\
                         '5jt Rupiah! Tunggu Apalagi?'

    if dpd == RamadanCampaign.T_MINUS_7:
        if product_code in ProductLineCodes.pedemtl():
            return (RamadanCampaign.EMAIL_REMINDER_1_PARTNER_TEMPLATE + '.html',
                    'pede_' + RamadanCampaign.EMAIL_REMINDER_1_TEMPLATE,
                    partner_subject_t7)
        elif product_code in ProductLineCodes.laku6():
            return (RamadanCampaign.EMAIL_REMINDER_1_PARTNER_TEMPLATE + '.html',
                    'laku6_' + RamadanCampaign.EMAIL_REMINDER_1_TEMPLATE,
                    partner_subject_t7)
        else:
            return (RamadanCampaign.EMAIL_REMINDER_1_TEMPLATE + '.html',
                    RamadanCampaign.EMAIL_REMINDER_1_TEMPLATE,
                    mtl_subject_t7)

    if dpd == RamadanCampaign.T_MINUS_3:
        if product_code in ProductLineCodes.pedemtl():
            return (RamadanCampaign.EMAIL_REMINDER_2_PARTNER_TEMPLATE + '.html',
                    'pede_' + RamadanCampaign.EMAIL_REMINDER_2_TEMPLATE,
                    partner_subject_t3)
        elif product_code in ProductLineCodes.laku6():
            return (RamadanCampaign.EMAIL_REMINDER_2_PARTNER_TEMPLATE + '.html',
                    'laku6_' + RamadanCampaign.EMAIL_REMINDER_2_TEMPLATE,
                    partner_subject_t3)
        else:
            return (RamadanCampaign.EMAIL_REMINDER_2_TEMPLATE + '.html',
                    RamadanCampaign.EMAIL_REMINDER_2_TEMPLATE,
                    mtl_subject_t3)


def get_sms_template_from_dpd_and_product_code(dpd, product_code):
    if dpd == RamadanCampaign.T_MINUS_6:
        if product_code in ProductLineCodes.pedemtl():
            return (RamadanCampaign.SMS_REMINDER_1_PARTNER_TEMPLATE + '.txt',
                    'pede_' + RamadanCampaign.SMS_REMINDER_1_TEMPLATE)
        elif product_code in ProductLineCodes.laku6():
            return (RamadanCampaign.SMS_REMINDER_1_PARTNER_TEMPLATE + '.txt',
                    'laku6_' + RamadanCampaign.SMS_REMINDER_1_TEMPLATE)
        else:
            return (RamadanCampaign.SMS_REMINDER_1_TEMPLATE + '.txt',
                    RamadanCampaign.SMS_REMINDER_1_TEMPLATE)

    if dpd == RamadanCampaign.T_MINUS_4:
        if product_code in ProductLineCodes.pedemtl():
            return (RamadanCampaign.SMS_REMINDER_2_PARTNER_TEMPLATE + '.txt',
                    'pede_' + RamadanCampaign.SMS_REMINDER_2_TEMPLATE)
        elif product_code in ProductLineCodes.laku6():
            return (RamadanCampaign.SMS_REMINDER_2_PARTNER_TEMPLATE + '.txt',
                    'laku6_' + RamadanCampaign.SMS_REMINDER_2_TEMPLATE)
        else:
            return (RamadanCampaign.SMS_REMINDER_2_TEMPLATE + '.txt',
                    RamadanCampaign.SMS_REMINDER_2_TEMPLATE)


def get_pn_template_and_content_from_dpd(dpd):
    moneywing = u'\U0001F4B8'
    present = u'\U0001F381'
    pn_content_dict = {
        RamadanCampaign.T_MINUS_7: 'Yuk,'
                                   'bayar cicilan JULO Anda dan menangkan hadiah 5 juta rupiah!' +
                                   moneywing,
        RamadanCampaign.T_MINUS_5: 'Psst.. cek email dari Kami tentang kejutan spesial untuk Anda!',
        RamadanCampaign.T_MINUS_3: 'Bayar cicilan Anda dan raih peluang jadi pemenang undian!' +
                                   moneywing + 'Tunggu apalagi?'
    }

    pn_title_dict = {
        RamadanCampaign.T_MINUS_7: 'Hi, Ada Kejutan Spesial dari JULO' + present,
        RamadanCampaign.T_MINUS_5: 'Kesempatan Baik Buat Anda!' + moneywing,
        RamadanCampaign.T_MINUS_3: 'Hadiah 5 Juta Menunggu Anda, nih!' + moneywing
    }

    pn_template_dict = {
        RamadanCampaign.T_MINUS_7: RamadanCampaign.PN_REMINDER_1_TEMPLATE,
        RamadanCampaign.T_MINUS_5: RamadanCampaign.PN_REMINDER_2_TEMPLATE,
        RamadanCampaign.T_MINUS_3: RamadanCampaign.PN_REMINDER_3_TEMPLATE
    }

    return pn_template_dict[dpd], pn_title_dict[dpd], pn_content_dict[dpd]


def get_pn_template_for_initiative3(reminder_type):
    moneywing = u'\U0001F4B8'
    present = u'\U0001F381'
    pn_content_dict = {
        RamadanCampaign.INITIATIVE3_REMINDER_1: 'Yuk, bayar cicilan JULO Anda dan menangkan hadiah '
                                                'total 20 juta rupiah!' + moneywing,
        RamadanCampaign.INITIATIVE3_REMINDER_2: 'Psst.. cek email dari Kami tentang '
                                                'kejutan spesial untuk Anda!' + moneywing,
        RamadanCampaign.INITIATIVE3_REMINDER_3: 'Bayar cicilan Anda dan raih peluang '
                                                'jadi pemenang undian!moneywing' + moneywing +
                                                ' Tunggu apalagi?',
        RamadanCampaign.INITIATIVE3_REMINDER_4: 'Bayar cicilan Anda dan raih peluang '
                                                'jadi pemenang undian!moneywing' + moneywing +
                                                ' Tunggu apalagi?',
        RamadanCampaign.INITIATIVE3_REMINDER_5: 'Bayar cicilan Anda dan raih peluang '
                                                'jadi pemenang undian!moneywing' + moneywing +
                                                ' Tunggu apalagi?',
    }

    pn_title_dict = {
        RamadanCampaign.INITIATIVE3_REMINDER_1: 'Hi, Kejutan Spesial dari JULO Menunggu Anda!' +
                                                present,
        RamadanCampaign.INITIATIVE3_REMINDER_2: 'Kesempatan Menarik Untuk Anda!' + moneywing,
        RamadanCampaign.INITIATIVE3_REMINDER_3: 'Hadiah 20 Juta Menunggu Anda!' + moneywing,
        RamadanCampaign.INITIATIVE3_REMINDER_4: 'Hadiah 20 Juta MASIH Menunggu Anda!' + moneywing,
        RamadanCampaign.INITIATIVE3_REMINDER_5: 'Yakin, Nggak Mau Hadiah Total 20jt?' + moneywing
    }

    pn_template_dict = {
        RamadanCampaign.INITIATIVE3_REMINDER_1: RamadanCampaign.INITIATIVE3_PN_REMINDER_1_TEMPLATE,
        RamadanCampaign.INITIATIVE3_REMINDER_2: RamadanCampaign.INITIATIVE3_PN_REMINDER_2_TEMPLATE,
        RamadanCampaign.INITIATIVE3_REMINDER_3: RamadanCampaign.INITIATIVE3_PN_REMINDER_3_TEMPLATE,
        RamadanCampaign.INITIATIVE3_REMINDER_4: RamadanCampaign.INITIATIVE3_PN_REMINDER_4_TEMPLATE,
        RamadanCampaign.INITIATIVE3_REMINDER_5: RamadanCampaign.INITIATIVE3_PN_REMINDER_5_TEMPLATE
    }

    return (pn_template_dict[reminder_type],
            pn_title_dict[reminder_type],
            pn_content_dict[reminder_type])


def get_email_template_for_initiative3(reminder_type, product_code):
    money_wing = u'\U0001F4B8'
    mtl_subject_1 = 'Spesial Untuk Anda yang Belum Membayar Pinjaman!'\
                    'Ada Total Hadiah 20 Juta!' + money_wing
    mtl_subject_2 = 'Pssst.. Hadiah Total 20 Juta Rupiah Menunggumu,'\
                    'nih! Klik Untuk Cari Tahu' + money_wing
    mtl_subject_3 = 'KESEMPATAN TERAKHIR Menangkan Total Hadiah 20jt'\
                    'Rupiah! Yakin Nggak Mau' + money_wing

    reminder1_subject = 'Bayar Cicilan JULO = Peluang Dapat Total 20jt Rupiah?'\
                        'Klik Untuk Cari Tahu Infonya!' + money_wing
    reminder2_subject = 'Pssst.. Total Hadiah 20jt Rupiah Masih Menunggu Anda!'\
                        'Yakin Mau Dilewatkan?' + money_wing
    reminder3_subject = 'KESEMPATAN TERAKHIR Menangkan Total Hadiah 20jt Rupiah!'\
                        + money_wing

    if reminder_type == RamadanCampaign.INITIATIVE3_REMINDER_1:
        if product_code in ProductLineCodes.pedemtl():
            return (RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_1_TEMPLATE + '.html',
                    'pede_' + RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_1_TEMPLATE,
                    reminder1_subject)
        elif product_code in ProductLineCodes.laku6():
            return (RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_1_TEMPLATE + '.html',
                    'laku6_' + RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_1_TEMPLATE,
                    reminder1_subject)
        else:
            return (RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_1_TEMPLATE + '.html',
                    RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_1_TEMPLATE,
                    mtl_subject_1)

    if reminder_type == RamadanCampaign.INITIATIVE3_REMINDER_2:
        if product_code in ProductLineCodes.pedemtl():
            return (RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_2_TEMPLATE + '.html',
                    'pede_' + RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_2_TEMPLATE,
                    reminder2_subject)
        elif product_code in ProductLineCodes.laku6():
            return (RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_2_TEMPLATE + '.html',
                    'laku6_' + RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_2_TEMPLATE,
                    reminder2_subject)
        else:
            return (RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_2_TEMPLATE + '.html',
                    RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_2_TEMPLATE,
                    mtl_subject_2)

    if reminder_type == RamadanCampaign.INITIATIVE3_REMINDER_3:
        if product_code in ProductLineCodes.pedemtl():
            return (RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_3_TEMPLATE + '.html',
                    'pede_' + RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_3_TEMPLATE,
                    reminder3_subject)
        elif product_code in ProductLineCodes.laku6():
            return (RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_3_TEMPLATE + '.html',
                    'laku6_' + RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_3_TEMPLATE,
                    reminder3_subject)
        else:
            return (RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_3_TEMPLATE + '.html',
                    RamadanCampaign.INITIATIVE3_EMAIL_REMINDER_3_TEMPLATE,
                    mtl_subject_3)


def get_sms_template_for_initiative3(reminder_type, product_code):
    if reminder_type == RamadanCampaign.INITIATIVE3_REMINDER_1:
        if product_code in ProductLineCodes.pedemtl():
            return (RamadanCampaign.INITIATIVE3_SMS_REMINDER_1_PARTNER_TEMPLATE + '.txt',
                    'pede_' + RamadanCampaign.INITIATIVE3_SMS_REMINDER_1_TEMPLATE)
        elif product_code in ProductLineCodes.laku6():
            return (RamadanCampaign.INITIATIVE3_SMS_REMINDER_1_PARTNER_TEMPLATE + '.txt',
                    'laku6_' + RamadanCampaign.INITIATIVE3_SMS_REMINDER_1_TEMPLATE)
        else:
            return (RamadanCampaign.INITIATIVE3_SMS_REMINDER_1_TEMPLATE + '.txt',
                    RamadanCampaign.INITIATIVE3_SMS_REMINDER_1_TEMPLATE)

    if reminder_type == RamadanCampaign.INITIATIVE3_REMINDER_2:
        if product_code in ProductLineCodes.pedemtl():
            return (RamadanCampaign.INITIATIVE3_SMS_REMINDER_2_PARTNER_TEMPLATE + '.txt',
                    'pede_' + RamadanCampaign.INITIATIVE3_SMS_REMINDER_2_TEMPLATE)
        elif product_code in ProductLineCodes.laku6():
            return (RamadanCampaign.INITIATIVE3_SMS_REMINDER_2_PARTNER_TEMPLATE + '.txt',
                    'laku6_' + RamadanCampaign.INITIATIVE3_SMS_REMINDER_2_TEMPLATE)
        else:
            return (RamadanCampaign.INITIATIVE3_SMS_REMINDER_2_TEMPLATE + '.txt',
                    RamadanCampaign.INITIATIVE3_SMS_REMINDER_2_TEMPLATE)

    if reminder_type == RamadanCampaign.INITIATIVE3_REMINDER_3:
        if product_code in ProductLineCodes.pedemtl():
            return (RamadanCampaign.INITIATIVE3_SMS_REMINDER_3_PARTNER_TEMPLATE + '.txt',
                    'pede_' + RamadanCampaign.INITIATIVE3_SMS_REMINDER_3_TEMPLATE)
        elif product_code in ProductLineCodes.laku6():
            return (RamadanCampaign.INITIATIVE3_SMS_REMINDER_3_PARTNER_TEMPLATE + '.txt',
                    'laku6_' + RamadanCampaign.INITIATIVE3_SMS_REMINDER_3_TEMPLATE)
        else:
            return (RamadanCampaign.INITIATIVE3_SMS_REMINDER_3_TEMPLATE + '.txt',
                    RamadanCampaign.INITIATIVE3_SMS_REMINDER_3_TEMPLATE)

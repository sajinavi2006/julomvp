from juloserver.grab.models import (
    PaymentGatewayBankCode,
    PaymentGatewayVendor
)
from juloserver.julo.models import Bank


def retroload_payment_gateway_vendor():
    PaymentGatewayVendor.objects.get_or_create(name='ayoconnect')


def retroload_payment_gateway_banks_code():
    bank_details = []
    ayoconnect_banks = [
        {
            'bank_code': '002',
            'bank_name': 'BANK BRI',
            'swift_bank_code': 'BRINIDJA'
        },
        {
            'bank_code': '008',
            'bank_name': 'BANK MANDIRI',
            'swift_bank_code': 'BMRIIDJA'
        },
        {
            'bank_code': '009',
            'bank_name': 'BANK BNI',
            'swift_bank_code': 'BNINIDJA'
        },
        {
            'bank_code': '011',
            'bank_name': 'BANK DANAMON',
            'swift_bank_code': 'BDINIDJA'
        },
        {
            'bank_code': '013',
            'bank_name': 'BANK PERMATA',
            'swift_bank_code': 'BBBAIDJA'
        },
        {
            'bank_code': '014',
            'bank_name': 'BANK BCA',
            'swift_bank_code': 'CENAIDJA'
        },
        {
            'bank_code': '016',
            'bank_name': 'BANK MAYBANK INDONESIA',
            'swift_bank_code': 'IBBKIDJA'
        },
        {
            'bank_code': '019',
            'bank_name': 'BANK PANIN',
            'swift_bank_code': 'PINBIDJA'
        },
        {
            'bank_code': '022',
            'bank_name': 'BANK CIMB NIAGA',
            'swift_bank_code': 'BNIAIDJA'
        },
        {
            'bank_code': '023',
            'bank_name': 'BANK UOB INDONESIA',
            'swift_bank_code': 'BBIJIDJA'
        },
        {
            'bank_code': '028',
            'bank_name': 'BANK OCBC NISP',
            'swift_bank_code': 'NISPIDJA'
        },
        {
            'bank_code': '031',
            'bank_name': 'CITIBANK INDONESIA',
            'swift_bank_code': 'CITIIDJX'
        },
        {
            'bank_code': '037',
            'bank_name': 'BANK ARTHA GRAHA',
            'swift_bank_code': 'ARTGIDJA'
        },
        {
            'bank_code': '042',
            'bank_name': 'MUFG BANK, LTD',
            'swift_bank_code': 'BOTKIDJX'
        },
        {
            'bank_code': '046',
            'bank_name': 'BANK DBS',
            'swift_bank_code': 'DBSBIDJA'
        },
        {
            'bank_code': '050',
            'bank_name': 'BANK STANCHART',
            'swift_bank_code': 'SCBLIDJX'
        },
        {
            'bank_code': '054',
            'bank_name': 'BANK CAPITAL',
            'swift_bank_code': 'BCIAIDJA'
        },
        {
            'bank_code': '061',
            'bank_name': 'BANK ANZ INDONESIA',
            'swift_bank_code': 'ANZBIDJX'
        },
        {
            'bank_code': '076',
            'bank_name': 'BANK BUMI ARTA',
            'swift_bank_code': 'BBAIIDJA'
        },
        {
            'bank_code': '087',
            'bank_name': 'BANK HSBC INDONESIA',
            'swift_bank_code': 'HSBCIDJA'
        },
        {
            'bank_code': '095',
            'bank_name': 'JTRUST BANK',
            'swift_bank_code': 'CICTIDJA'
        },
        {
            'bank_code': '097',
            'bank_name': 'BANK MAYAPADA',
            'swift_bank_code': 'MAYAIDJA'
        },
        {
            'bank_code': '110',
            'bank_name': 'BANK BJB',
            'swift_bank_code': 'PDJBIDJA'
        },
        {
            'bank_code': '111',
            'bank_name': 'BANK DKI',
            'swift_bank_code': 'BDKIIDJ1'
        },
        {
            'bank_code': '112',
            'bank_name': 'BPD DIY',
            'swift_bank_code': 'PDYKIDJ1'
        },
        {
            'bank_code': '113',
            'bank_name': 'BANK JATENG',
            'swift_bank_code': 'PDJGIDJ1'
        },
        {
            'bank_code': '114',
            'bank_name': 'BANK JATIM',
            'swift_bank_code': 'PDJTIDJ1'
        },
        {
            'bank_code': '115',
            'bank_name': 'BANK JAMBI',
            'swift_bank_code': 'PDJMIDJ1'
        },
        {
            'bank_code': '116',
            'bank_name': 'BANK ACEH SYARIAH',
            'swift_bank_code': 'SYACIDJ1'
        },
        {
            'bank_code': '117',
            'bank_name': 'BPD SUMUT',
            'swift_bank_code': 'PDSUIDJ1'
        },
        {
            'bank_code': '118',
            'bank_name': 'BANK NAGARI',
            'swift_bank_code': 'PDSBIDJ1'
        },
        {
            'bank_code': '119',
            'bank_name': 'PT BPD Riau Kepri Syariah (Perseroda)',
            'swift_bank_code': 'PDRIIDJA'
        },
        {
            'bank_code': '120',
            'bank_name': 'BANK SUMSELBABEL',
            'swift_bank_code': 'BSSPIDSP'
        },
        {
            'bank_code': '121',
            'bank_name': 'BANK LAMPUNG',
            'swift_bank_code': 'PDLPIDJ1'
        },
        {
            'bank_code': '122',
            'bank_name': 'BANK KALSEL',
            'swift_bank_code': 'PDKSIDJ1'
        },
        {
            'bank_code': '123',
            'bank_name': 'BANK KALBAR',
            'swift_bank_code': 'PDKBIDJ1'
        },
        {
            'bank_code': '124',
            'bank_name': 'BPD KALTIM KALTARA',
            'swift_bank_code': 'PDKTIDJ1'
        },
        {
            'bank_code': '125',
            'bank_name': 'BPD KALTENG',
            'swift_bank_code': 'PDKGIDJ1'
        },
        {
            'bank_code': '126',
            'bank_name': 'BANK SULSELBAR',
            'swift_bank_code': 'PDWSIDJA'
        },
        {
            'bank_code': '127',
            'bank_name': 'BPD SULUT',
            'swift_bank_code': 'PDWUIDJ1'
        },
        {
            'bank_code': '129',
            'bank_name': 'BPD BALI',
            'swift_bank_code': 'ABALIDBS'
        },
        {
            'bank_code': '130',
            'bank_name': 'BANK NTT',
            'swift_bank_code': 'PDNTIDJA'
        },
        {
            'bank_code': '131',
            'bank_name': 'BANK MALUKU',
            'swift_bank_code': 'PDMLIDJ1'
        },
        {
            'bank_code': '132',
            'bank_name': 'BANK PAPUA',
            'swift_bank_code': 'PDIJIDJ1'
        },
        {
            'bank_code': '133',
            'bank_name': 'BANK BENGKULU',
            'swift_bank_code': 'PDBKIDJ1'
        },
        {
            'bank_code': '134',
            'bank_name': 'BANK SULTENG',
            'swift_bank_code': 'PDWGIDJ1'
        },
        {
            'bank_code': '135',
            'bank_name': 'BANK SULTRA',
            'swift_bank_code': 'PDWRIDJ1'
        },
        {
            'bank_code': '137',
            'bank_name': 'BPD BANTEN',
            'swift_bank_code': 'PDBBIDJ1'
        },
        {
            'bank_code': '145',
            'bank_name': 'BANK BNP',
            'swift_bank_code': 'BNPAIDJA'
        },
        {
            'bank_code': '147',
            'bank_name': 'BANK MUAMALAT',
            'swift_bank_code': 'MUABIDJA'
        },
        {
            'bank_code': '151',
            'bank_name': 'BANK MESTIKA',
            'swift_bank_code': 'MEDHIDSl'
        },
        {
            'bank_code': '152',
            'bank_name': 'BANK SHINHAN INDONESIA',
            'swift_bank_code': 'MEEKIDJ1'
        },
        {
            'bank_code': '153',
            'bank_name': 'BANK SINARMAS',
            'swift_bank_code': 'SBJKIDJA'
        },
        {
            'bank_code': '157',
            'bank_name': 'BANK MASPION',
            'swift_bank_code': 'MASDIDJ1'
        },
        {
            'bank_code': '161',
            'bank_name': 'BANK GANESHA',
            'swift_bank_code': 'GNESIDJA'
        },
        {
            'bank_code': '164',
            'bank_name': 'BANK ICBC INDONESIA',
            'swift_bank_code': 'ICBKIDJA'
        },
        {
            'bank_code': '167',
            'bank_name': 'BANK QNB INDONESIA',
            'swift_bank_code': 'AWANIDJA'
        },
        {
            'bank_code': '200',
            'bank_name': 'BANK BTN',
            'swift_bank_code': 'BTANIDJA'
        },
        {
            'bank_code': '212',
            'bank_name': 'BANK WOORI INDONESIA',
            'swift_bank_code': 'BSDRIDJA'
        },
        {
            'bank_code': '213',
            'bank_name': 'BANK BTPN',
            'swift_bank_code': 'SUNIIDJA'
        },
        {
            'bank_code': '425',
            'bank_name': 'BANK BJB SYARIAH',
            'swift_bank_code': 'SYJBIDJ1'
        },
        {
            'bank_code': '426',
            'bank_name': 'BANK MEGA',
            'swift_bank_code': 'MEGAIDJA'
        },
        {
            'bank_code': '441',
            'bank_name': 'KB Bukopin',
            'swift_bank_code': 'BBUKIDJA'
        },
        {
            'bank_code': '451',
            'bank_name': 'BSI',
            'swift_bank_code': 'BSMDIDJA'
        },
        {
            'bank_code': '472',
            'bank_name': 'BANK JASA JAKARTA',
            'swift_bank_code': 'JSABIDJ1'
        },
        {
            'bank_code': '484',
            'bank_name': 'KEB HANA',
            'swift_bank_code': 'HNBNIDJA'
        },
        {
            'bank_code': '485',
            'bank_name': 'BANK MNC',
            'swift_bank_code': 'BUMIIDJA'
        },
        {
            'bank_code': '490',
            'bank_name': 'Bank Neo Commerce',
            'swift_bank_code': 'YUDBIDJ1'
        },
        {
            'bank_code': '494',
            'bank_name': 'BANK RAYA INDONESIA',
            'swift_bank_code': 'AGTBIDJA'
        },
        {
            'bank_code': '501',
            'bank_name': 'BANK DIGITAL BCA',
            'swift_bank_code': 'ROYBIDJ1'
        },
        {
            'bank_code': '503',
            'bank_name': 'BANK NOBU',
            'swift_bank_code': 'LFIBIDJ1'
        },
        {
            'bank_code': '506',
            'bank_name': 'BANK MEGA SYARIAH',
            'swift_bank_code': 'BUTGIDJ1'
        },
        {
            'bank_code': '513',
            'bank_name': 'BANK INA PERDANA',
            'swift_bank_code': 'IAPTIDJA'
        },
        {
            'bank_code': '517',
            'bank_name': 'BANK PANIN SYARIAH',
            'swift_bank_code': 'ARFAIDJ1'
        },
        {
            'bank_code': '521',
            'bank_name': 'SYARIAH BUKOPIN',
            'swift_bank_code': 'SDOBIDJ1'
        },
        {
            'bank_code': '523',
            'bank_name': 'BANK SAHABAT SAMPOERNA',
            'swift_bank_code': 'BDIPIDJ1'
        },
        {
            'bank_code': '531',
            'bank_name': 'BANK AMAR',
            'swift_bank_code': 'LOMAIDJ1'
        },
        {
            'bank_code': '535',
            'bank_name': 'SEABANK',
            'swift_bank_code': 'SSPIIDJA'
        },
        {
            'bank_code': '536',
            'bank_name': 'BANK BCA SYARIAH',
            'swift_bank_code': 'SYCAIDJ1'
        },
        {
            'bank_code': '542',
            'bank_name': 'BANK JAGO',
            'swift_bank_code': 'ATOSIDJ1'
        },
        {
            'bank_code': '547',
            'bank_name': 'BTPN SYARIAH',
            'swift_bank_code': 'PUBAIDJ1'
        },
        {
            'bank_code': '548',
            'bank_name': 'BANK MULTIARTA SENTOSA',
            'swift_bank_code': 'BMSEIDJA'
        },
        {
            'bank_code': '553',
            'bank_name': 'BANK MAYORA',
            'swift_bank_code': 'MAYOIDJA'
        },
        {
            'bank_code': '555',
            'bank_name': 'BANK INDEX',
            'swift_bank_code': 'BIDXIDJA'
        },
        {
            'bank_code': '564',
            'bank_name': 'BANK MANTAP',
            'swift_bank_code': 'SIHBIDJ1'
        },

        {
            'bank_code': '566',
            'bank_name': 'BANK VICTORIA',
            'swift_bank_code': 'VICTIDJ1'
        },
        {
            'bank_code': '567',
            'bank_name': 'Allo Bank',
            'swift_bank_code': 'HRDAIDJ1'
        },
        {
            'bank_code': '947',
            'bank_name': 'BANK ALADIN SYARIAH',
            'swift_bank_code': 'NETBIDJA'
        },

        {
            'bank_code': '949',
            'bank_name': 'BANK CTBC INDONESIA',
            'swift_bank_code': 'CTCBIDJA'
        },
        {
            'bank_code': '950',
            'bank_name': 'COMMONWEALTH INDONESIA',
            'swift_bank_code': 'BICNIDJA'
        },
        {
            'bank_code': 'B00',
            'bank_name': 'BANK DANAMON INDONESIA SYARIAH',
            'swift_bank_code': 'SYBDIDJ1'
        },

        {
            'bank_code': 'B01',
            'bank_name': 'BANK CIMB NIAGA SYARIAH',
            'swift_bank_code': 'SYNAIDJ1'
        },
        {
            'bank_code': 'B02',
            'bank_name': 'BTN SYARIAH',
            'swift_bank_code': 'SYBTIDJ1'
        },
        {
            'bank_code': 'B03',
            'bank_name': 'BANK PERMATA SYARIAH',
            'swift_bank_code': 'SYBBIDJ1'
        },
        {
            'bank_code': 'B05',
            'bank_name': 'KUSTODIAN SENTRAL EFEK INDONESIA',
            'swift_bank_code': 'KSEIIDJ1'
        },
        {
            'bank_code': 'B06',
            'bank_name': 'BANK JATENG SYARIAH',
            'swift_bank_code': 'SYJGIDJ1'
        },
        {
            'bank_code': 'B07',
            'bank_name': 'BANK SINARMAS SYARIAH',
            'swift_bank_code': 'SYTBIDJ1'
        },
        {
            'bank_code': 'B08',
            'bank_name': 'BANK JATIM SYARIAH',
            'swift_bank_code': 'SYJTIDJ1'
        },

        {
            'bank_code': 'B10',
            'bank_name': 'BANK DKI SYARIAH',
            'swift_bank_code': 'SYDKIDJ1'
        },
        {
            'bank_code': 'B11',
            'bank_name': 'BANK MAYBANK INDONESIA SYARIAH',
            'swift_bank_code': 'SYBKIDJ1'
        },
        {
            'bank_code': 'B12',
            'bank_name': 'BANK JAGO SYARIAH',
            'swift_bank_code': 'SYATIDJ1'
        },
        {
            'bank_code': 'B14',
            'bank_name': 'BPD DIY SYARIAH',
            'swift_bank_code': 'SYYKIDJ1'
        },
        {
            'bank_code': 'B15',
            'bank_name': 'BANK NAGARI SYARIAH',
            'swift_bank_code': 'SYSBIDJ1'
        },
        {
            'bank_code': 'B16',
            'bank_name': 'BANK SUMSELBABEL SYARIAH',
            'swift_bank_code': 'SYSSIDJ1'
        },
        {
            'bank_code': 'B17',
            'bank_name': 'BANK KALSEL SYARIAH',
            'swift_bank_code': 'SYKSIDJ1'
        },

        {
            'bank_code': 'B18',
            'bank_name': 'BANK KALBAR SYARIAH',
            'swift_bank_code': 'SYKBIDJ1'
        },
        {
            'bank_code': 'B21',
            'bank_name': 'BPD SUMUT SYARIAH',
            'swift_bank_code': 'SYSUIDJ1'
        },
        {
            'bank_code': 'B22',
            'bank_name': 'BANK JAMBI SYARIAH',
            'swift_bank_code': 'SYJMIDJ1'
        },

        {
            'bank_code': 'B23',
            'bank_name': 'BANK SULSELBAR SYARIAH',
            'swift_bank_code': 'SYWSIDJ1'
        },
        {
            'bank_code': 'B24',
            'bank_name': 'BPD KALTIM KALTARA SYARIAH',
            'swift_bank_code': 'SYKTIDJ1'
        },
        {
            'bank_code': 'B25',
            'bank_name': 'BPD NTB SYARIAH',
            'swift_bank_code': 'PDNBIDJ1'
        },
        {
            'bank_code': 'B26',
            'bank_name': 'OCBC NISP SYARIAH',
            'swift_bank_code': 'SYONIDJ1'
        },
        {
            'bank_code': 'B27',
            'bank_name': 'Bank Resona Perdania',
            'swift_bank_code': 'BPIAIDJA'
        },
        {
            'bank_code': 'B28',
            'bank_name': 'Bank IBK Indonesia',
            'swift_bank_code': 'IBKOIDJA'
        },
        {
            'bank_code': 'B29',
            'bank_name': 'Bank China Construction',
            'swift_bank_code': 'MCORIDJA'
        },
        {
            'bank_code': 'B30',
            'bank_name': 'Bank of China',
            'swift_bank_code': 'BKCHIDJA'
        },
        {
            'bank_code': 'B31',
            'bank_name': 'Bank of America NA',
            'swift_bank_code': 'BOFAID2X'
        },
        {
            'bank_code': 'B32',
            'bank_name': 'Bank OKE Indonesia',
            'swift_bank_code': 'LMANIDJ1'
        },
        {
            'bank_code': 'B33',
            'bank_name': 'Bank Mizuho Indonesia',
            'swift_bank_code': 'MHCCIDJA'
        },
        {
            'bank_code': 'B34',
            'bank_name': 'Bank BNP Paribas Indonesia',
            'swift_bank_code': 'BNPAIDJA'
        },
        {
            'bank_code': 'B35',
            'bank_name': 'Bank Panin Dubai Syariah',
            'swift_bank_code': 'ARFAIDJ1'
        },
        {
            'bank_code': 'B36',
            'bank_name': 'Shopeepay',
            'swift_bank_code': 'APIDIDJ1'
        },
        {
            'bank_code': 'B37',
            'bank_name': 'Dana',
            'swift_bank_code': 'DANAIDJ1'
        }
    ]

    payment_gateway_vendor, _ = PaymentGatewayVendor.objects.get_or_create(name='ayoconnect')

    for ayoconnect_bank in ayoconnect_banks:
        bank = Bank.objects.filter(bank_code=ayoconnect_bank['bank_code'],
                                   swift_bank_code=ayoconnect_bank['swift_bank_code']).first()

        if bank:
            data = {
                'swift_bank_code': ayoconnect_bank['swift_bank_code'],
                'bank_id': bank.id,
                'payment_gateway_vendor': payment_gateway_vendor
            }
            bank_details.append(PaymentGatewayBankCode(**data))
        else:
            swift_bank_code = None

            if (ayoconnect_bank['bank_code'] == '087' and
                    ayoconnect_bank['swift_bank_code'] == 'HSBCIDJA'):
                swift_bank_code = 'EKONIDJA'
            elif (ayoconnect_bank['bank_code'] == '111' and
                  ayoconnect_bank['swift_bank_code'] == 'BDKIIDJ1'):
                swift_bank_code = 'SYDKIDJ1'
            elif (ayoconnect_bank['bank_code'] == '118' and
                  ayoconnect_bank['swift_bank_code'] == 'PDSBIDJ1'):
                swift_bank_code = 'PDSBIDSP'
            elif (ayoconnect_bank['bank_code'] == '126' and
                  ayoconnect_bank['swift_bank_code'] == 'PDWSIDJA'):
                swift_bank_code = 'PDWSIDJ1'
            elif (ayoconnect_bank['bank_code'] == '130' and
                  ayoconnect_bank['swift_bank_code'] == 'PDNTIDJA'):
                swift_bank_code = 'PDNTIDJ1'
            elif (ayoconnect_bank['bank_code'] == '145' and
                  ayoconnect_bank['swift_bank_code'] == 'BNPAIDJA'):
                swift_bank_code = 'NUPAIDJ6'
            elif (ayoconnect_bank['bank_code'] == '157' and
                  ayoconnect_bank['swift_bank_code'] == 'MASDIDJ1'):
                swift_bank_code = 'MASDIDJS'
            elif (ayoconnect_bank['bank_code'] == '212' and
                  ayoconnect_bank['swift_bank_code'] == 'BSDRIDJA'):
                swift_bank_code = 'HVBKIDJA'
            elif (ayoconnect_bank['bank_code'] == '213' and
                  ayoconnect_bank['swift_bank_code'] == 'SUNIIDJA'):
                swift_bank_code = 'BTPNIDJA'
            elif (ayoconnect_bank['bank_code'] == '513' and
                  ayoconnect_bank['swift_bank_code'] == 'IAPTIDJA'):
                swift_bank_code = 'INPBIDJ1'
            elif (ayoconnect_bank['bank_code'] == '566' and
                  ayoconnect_bank['swift_bank_code'] == 'VICTIDJ1'):
                swift_bank_code = 'BVICIDJA'
            elif (ayoconnect_bank['bank_code'] == '947' and
                  ayoconnect_bank['swift_bank_code'] == 'NETBIDJA'):
                swift_bank_code = 'MBBEIDJA'

            if swift_bank_code:
                bank = Bank.objects.filter(bank_code=ayoconnect_bank['bank_code'],
                                           swift_bank_code=swift_bank_code).last()
                if bank:
                    data = {
                        'swift_bank_code': ayoconnect_bank['swift_bank_code'],
                        'bank_id': bank.id,
                        'payment_gateway_vendor': payment_gateway_vendor
                    }
                    bank_details.append(PaymentGatewayBankCode(**data))

    PaymentGatewayBankCode.objects.bulk_create(bank_details, batch_size=50)

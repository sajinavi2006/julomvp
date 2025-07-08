from builtins import object
from collections import namedtuple
import logging
from django.db.models import Q
from juloserver.julo.models import Bank as BankModel

logger = logging.getLogger(__name__)

BANKS_VERSION = '2.0.0'


class BankCodes(object):
    BCA = '014'
    BCA_SYARIAH = '536'
    MANDIRI = '008'
    SYARIAH_MANDIRI = '451'
    BRI = '002'
    SYARIAH_BRI = '422'
    BNI = '009'
    BNI_SYARIAH = '009'
    CIMB_NIAGA = '022'
    DANAMON = '011'
    PERMATA = '013'
    PANIN = '019'
    PANIN_SYARIAH = '517'
    BTN = '200'
    MEGA = '426'
    SYARIAH_MEGA = '506'
    ANTAR_DAERAH = '088'
    ARTHA_GRAHA = '037'
    BUKOPIN = '441'
    BUMI_ARTA = '076'
    EKONOMI = '087'
    GANESHA = '161'
    HANA = '484'
    HIMPUNAN_SAUDARA = '212'
    MNC = '485'
    ICBC = '164'
    INDEX_SELINDO = '555'
    MAYBANK = '016'
    MASPION = '157'
    MAYAPADA = '097'
    MESTIKA_DHARMA = '151'
    METRO_EXPRESS = '152'
    MUAMALAT = '147'
    MUTIARA = '095'
    NUSANTARA_PARAHYANGAN = '145'
    OCBC_NISP = '028'
    INDIA = '146'
    AGRONIAGA = '494'
    SBI = '498'
    SINARMAS = '153'
    UOB = '023'
    QNB_KESAWAN = '167'
    ANGLOMAS = '531'
    ANDARA = ''  # does not exist yet
    ARTOS = '542'
    BISNIS = '459'
    DINAR = '526'
    FAMA = '562'
    HARDA = '567'
    INA_PERDANA = '513'
    BJB_SYARIAH = '425'
    JASA_JAKARTA = '427'
    KESEJAHTERAAN_EKONOMI = '515'
    MAYORA = '553'
    MITRA_NIAGA = '491'
    MULTI_ARTA_SENTOSA = '548'
    NATIONALNOBU = '503'
    PUNDI = '558'
    ROYAL = '501'
    SAHABAT_PURBA_DANARTA = '547'
    SAHABAT_SAMPOERNA = '523'
    SINAR_HARAPAN_BALI = '564'
    SYARIAH_BUKOPIN = '521'
    BTPN = '213'
    VICTORIA = '566'
    VICTORIA_SYARIAH = '405'
    YUDHA_BHAKTI = '490'
    CENTRATAMA = '559'
    PRIMA_MASTER = '520'
    BPD_SULTRA = '135'
    BPD_DIY = '112'
    BPD_KALTIM = '124'
    DKI = '111'
    BPD_ACEH = '116'
    BPD_KALTENG = '125'
    BPD_JAMBI = '115'
    BPD_SULSELBAR = '126'
    BPD_LAMPUNG = '121'
    BPD_RIAU_KEPRI = '119'
    BPD_SUMBAR = '118'
    BJB = '110'
    BPD_MALUKU = '131'
    BPD_BENGKULU = '133'
    BPD_JATENG = '113'
    BPD_JATIM = '114'
    BPD_KALBAR = '123'
    BPD_NTB = '128'
    BPD_NTT = '130'
    BPD_SULTENG = '134'
    BPD_SULUT = '127'
    BPD_BALI = '129'
    BPD_KALSEL = '122'
    BPD_PAPUA = '132'
    BPD_SUMSEL_BABEL = '120'
    BPD_SUMUT = '117'
    COMMONWEALTH = '950'
    AGRIS = '945'
    ANZ = '061'
    BNP_PARIBAS = '057'
    CAPITAL = '054'
    DBS = '046'
    MAYBANK_SYARIAH = '947'
    MIZUHO = '048'
    RABOBANK = '060'
    RESONA_PERDANIA = '047'
    WINDU_KENTJANA = '162'
    WOORI = '068'
    CHINATRUST = '949'
    SUMITOMO_MITSUI = '045'
    AMERICA = '033'
    BOC = '069'
    CITIBANK = '031'
    DEUTSCHE = '067'
    JPMORGAN = '032'
    STANDARD_CHARTERED = '050'
    BANGKOK = '040'
    TOKYO_MITSUBISHI = '042'
    HSBC = '041'
    RBS = '052'
    BPD_JAMBI_UUS = BPD_JAMBI
    BPD_NTB_UUS = BPD_NTB
    BPD_RIAU_KEPRI_UUS = BPD_RIAU_KEPRI
    BPD_SUMBAR_UUS = BPD_SUMBAR
    BPD_KALBAR_UUS = BPD_KALBAR
    BPD_KALSEL_UUS = BPD_KALSEL
    BPD_KALTIM_UUS = BPD_KALTIM
    BPD_SUMSEL_BABEL_UUS = BPD_SUMSEL_BABEL
    DKI_UUS = DKI
    BPD_ACEH_UUS = BPD_ACEH
    BPD_SUMUT_UUS = BPD_SUMUT
    BPD_DIY_UUS = BPD_DIY
    BPD_JATENG_UUS = BPD_JATENG
    BPD_JATIM_UUS = BPD_JATIM
    BPD_SULSELBAR_UUS = BPD_SULSELBAR
    HSBC_UUS = HSBC
    EKSPOR = '003'
    BTPN_UUS = BTPN
    BTN_UUS = BTN
    CIMB_NIAGA_UUS = CIMB_NIAGA
    OCBC_NISP_UUS = OCBC_NISP
    DANAMON_UUS = DANAMON
    PERMATA_UUS = PERMATA
    DANA_BILLER = '880'


class XenditBankCode(object):
    BCA = 'BCA'
    BCA_SYARIAH = 'BCA_SYR'
    MANDIRI = 'MANDIRI'
    SYARIAH_MANDIRI = 'MANDIRI_SYR'
    BRI = 'BRI'
    SYARIAH_BRI = 'BRI_SYR'
    BNI = 'BNI'
    BNI_SYARIAH = 'BNI_SYR'
    CIMB_NIAGA = 'CIMB'
    DANAMON = 'DANAMON'
    PERMATA = 'PERMATA'
    PANIN = 'PANIN'
    PANIN_SYARIAH = 'PANIN_SYR'
    BTN = 'BTN'
    MEGA = 'MEGA'
    SYARIAH_MEGA = 'MEGA_SYR'
    ANTAR_DAERAH = 'CCB'
    ARTHA_GRAHA = 'ARTHA'
    BUKOPIN = 'BUKOPIN'
    BUMI_ARTA = 'BUMI_ARTA'
    EKONOMI = 'HSBC'
    GANESHA = 'GANESHA'
    HANA = 'HANA'
    HIMPUNAN_SAUDARA = 'HIMPUNAN_SAUDARA'
    MNC = 'MNC_INTERNASIONAL'
    ICBC = 'ICBC'
    INDEX_SELINDO = 'INDEX_SELINDO'
    MAYBANK = 'MAYBANK'
    MASPION = 'MASPION'
    MAYAPADA = 'MAYAPADA'
    MESTIKA_DHARMA = 'MESTIKA_DHARMA'
    METRO_EXPRESS = 'SHINHAN'
    MUAMALAT = 'MUAMALAT'
    MUTIARA = 'JTRUST'
    NUSANTARA_PARAHYANGAN = 'NUSANTARA_PARAHYANGAN'
    OCBC_NISP = 'OCBC'
    INDIA = 'INDIA'
    AGRONIAGA = 'AGRONIAGA'
    SBI = 'SBI_INDONESIA'
    SINARMAS = 'SINARMAS'
    UOB = 'UOB'
    QNB_KESAWAN = 'QNB_INDONESIA'
    ANGLOMAS = 'ANGLOMAS'
    ANDARA = 'ANDARA'
    ARTOS = 'ARTOS'
    BISNIS = 'BISNIS_INTERNASIONAL'
    DINAR = 'DINAR_INDONESIA'
    FAMA = 'FAMA'
    HARDA = 'HARDA_INTERNASIONAL'
    INA_PERDANA = 'INA_PERDANA'
    BJB_SYARIAH = 'BJB_SYR'
    JASA_JAKARTA = 'JASA_JAKARTA'
    KESEJAHTERAAN_EKONOMI = 'KESEJAHTERAAN_EKONOMI'
    MAYORA = 'MAYORA'
    MITRA_NIAGA = 'MITRA_NIAGA'
    MULTI_ARTA_SENTOSA = 'MULTI_ARTA_SENTOSA'
    NATIONALNOBU = 'NATIONALNOBU'
    PUNDI = 'BANTEN'
    ROYAL = 'ROYAL'
    SAHABAT_PURBA_DANARTA = 'BTPN_SYARIAH'
    SAHABAT_SAMPOERNA = 'SAHABAT_SAMPOERNA'
    SINAR_HARAPAN_BALI = 'MANDIRI_TASPEN'
    SYARIAH_BUKOPIN = 'BUKOPIN_SYR'
    BTPN = 'TABUNGAN_PENSIUNAN_NASIONAL'
    VICTORIA = 'VICTORIA_INTERNASIONAL'
    VICTORIA_SYARIAH = 'VICTORIA_SYR'
    YUDHA_BHAKTI = 'YUDHA_BHAKTI'
    CENTRATAMA = 'CENTRATAMA'
    PRIMA_MASTER = 'PRIMA_MASTER'
    BPD_SULTRA = 'SULAWESI_TENGGARA'
    BPD_DIY = 'DAERAH_ISTIMEWA'
    BPD_KALTIM = 'KALIMANTAN_TIMUR'
    DKI = 'DKI'
    BPD_ACEH = 'ACEH'
    BPD_KALTENG = 'KALIMANTAN_TENGAH'
    BPD_JAMBI = 'JAMBI'
    BPD_SULSELBAR = 'SULSELBAR'
    BPD_LAMPUNG = 'LAMPUNG'
    BPD_RIAU_KEPRI = 'RIAU_DAN_KEPRI'
    BPD_SUMBAR = 'SUMATERA_BARAT'
    BJB = 'BJB'
    BPD_MALUKU = 'MALUKU'
    BPD_BENGKULU = 'BENGKULU'
    BPD_JATENG = 'JAWA_TENGAH'
    BPD_JATIM = 'JAWA_TIMUR'
    BPD_KALBAR = 'KALIMANTAN_BARAT'
    BPD_NTB = 'NUSA_TENGGARA_BARAT'
    BPD_NTT = 'NUSA_TENGGARA_TIMUR'
    BPD_SULTENG = 'SULAWESI'
    BPD_SULUT = 'SULUT'
    BPD_BALI = 'BALI'
    BPD_KALSEL = 'KALIMANTAN_SELATAN'
    BPD_PAPUA = 'PAPUA'
    BPD_SUMSEL_BABEL = 'SUMSEL_DAN_BABEL'
    BPD_SUMUT = 'SUMUT'
    COMMONWEALTH = 'COMMONWEALTH'
    AGRIS = 'AGRIS'
    ANZ = 'ANZ'
    BNP_PARIBAS = 'BNP_PARIBAS'
    CAPITAL = 'CAPITAL'
    DBS = 'DBS'
    MAYBANK_SYARIAH = 'MAYBANK_SYR'
    MIZUHO = 'MIZUHO'
    RABOBANK = 'RABOBANK'
    RESONA_PERDANIA = 'RESONA'
    WINDU_KENTJANA = 'CCB'
    WOORI = 'WOORI'
    CHINATRUST = 'CHINATRUST'
    SUMITOMO_MITSUI = 'MITSUI'
    AMERICA = 'BAML'
    BOC = 'BOC'
    CITIBANK = 'CITIBANK'
    DEUTSCHE = 'DEUTSCHE'
    JPMORGAN = 'JPMORGAN'
    STANDARD_CHARTERED = 'STANDARD_CHARTERED'
    BANGKOK = 'BANGKOK'
    TOKYO_MITSUBISHI = 'TOKYO'
    HSBC = 'HSBC'
    RBS = 'RBS'
    BPD_JAMBI_UUS = 'JAMBI_UUS'
    BPD_NTB_UUS = 'NUSA_TENGGARA_BARAT_UUS'
    BPD_RIAU_KEPRI_UUS = 'RIAU_DAN_KEPRI_UUS'
    BPD_SUMBAR_UUS = 'SUMATERA_BARAT_UUS'
    BPD_KALBAR_UUS = 'KALIMANTAN_BARAT_UUS'
    BPD_KALSEL_UUS = 'KALIMANTAN_SELATAN_UUS'
    BPD_KALTIM_UUS = 'KALIMANTAN_TIMUR_UUS'
    BPD_SUMSEL_BABEL_UUS = 'SUMSEL_DAN_BABEL_UUS'
    DKI_UUS = 'DKI_UUS'
    BPD_ACEH_UUS = 'ACEH_UUS'
    BPD_SUMUT_UUS = 'SUMUT_UUS'
    BPD_DIY_UUS = 'DAERAH_ISTIMEWA_UUS'
    BPD_JATENG_UUS = 'JAWA_TENGAH_UUS'
    BPD_JATIM_UUS = 'JAWA_TIMUR_UUS'
    BPD_SULSELBAR_UUS = 'SULSELBAR_UUS'
    HSBC_UUS = 'HSBC_UUS'
    EKSPOR = 'EXIMBANK'
    BTPN_UUS = 'BTPN_SYARIAH'
    BTN_UUS = 'BTN_UUS'
    CIMB_NIAGA_UUS = 'CIMB_UUS'
    OCBC_NISP_UUS = 'OCBC_UUS'
    DANAMON_UUS = 'DANAMON_UUS'
    PERMATA_UUS = 'PERMATA_UUS'


class InstamoneyBankCode(object):
    BCA = 'BCA'
    BCA_SYARIAH = 'BCA_SYR'
    MANDIRI = 'MANDIRI'
    SYARIAH_MANDIRI = 'MANDIRI_SYR'
    BRI = 'BRI'
    SYARIAH_BRI = 'BRI_SYR'
    BNI = 'BNI'
    BNI_SYARIAH = 'BNI_SYR'
    CIMB_NIAGA = 'CIMB'
    DANAMON = 'DANAMON'
    PERMATA = 'PERMATA'
    PANIN = 'PANIN'
    PANIN_SYARIAH = 'PANIN_SYR'
    BTN = 'BTN'
    MEGA = 'MEGA'
    SYARIAH_MEGA = 'MEGA_SYR'
    ANTAR_DAERAH = 'CCB'
    ARTHA_GRAHA = 'ARTHA'
    BUKOPIN = 'BUKOPIN'
    BUMI_ARTA = 'BUMI_ARTA'
    EKONOMI = 'HSBC'
    GANESHA = 'GANESHA'
    HANA = 'HANA'
    HIMPUNAN_SAUDARA = 'HIMPUNAN_SAUDARA'
    MNC = 'MNC_INTERNASIONAL'
    ICBC = 'ICBC'
    INDEX_SELINDO = 'INDEX_SELINDO'
    MAYBANK = 'MAYBANK'
    MASPION = 'MASPION'
    MAYAPADA = 'MAYAPADA'
    MESTIKA_DHARMA = 'MESTIKA_DHARMA'
    METRO_EXPRESS = 'SHINHAN'
    MUAMALAT = 'MUAMALAT'
    MUTIARA = 'JTRUST'
    NUSANTARA_PARAHYANGAN = 'NUSANTARA_PARAHYANGAN'
    OCBC_NISP = 'OCBC'
    INDIA = 'INDIA'
    AGRONIAGA = 'AGRONIAGA'
    SBI = 'SBI_INDONESIA'
    SINARMAS = 'SINARMAS'
    UOB = 'UOB'
    QNB_KESAWAN = 'QNB_INDONESIA'
    ANGLOMAS = 'ANGLOMAS'
    ANDARA = 'ANDARA'
    ARTOS = 'ARTOS'
    BISNIS = 'BISNIS_INTERNASIONAL'
    DINAR = 'DINAR_INDONESIA'
    FAMA = 'FAMA'
    HARDA = 'HARDA_INTERNASIONAL'
    INA_PERDANA = 'INA_PERDANA'
    BJB_SYARIAH = 'BJB_SYR'
    JASA_JAKARTA = 'JASA_JAKARTA'
    KESEJAHTERAAN_EKONOMI = 'KESEJAHTERAAN_EKONOMI'
    MAYORA = 'MAYORA'
    MITRA_NIAGA = 'MITRA_NIAGA'
    MULTI_ARTA_SENTOSA = 'MULTI_ARTA_SENTOSA'
    NATIONALNOBU = 'NATIONALNOBU'
    PUNDI = 'BANTEN'
    ROYAL = 'ROYAL'
    SAHABAT_PURBA_DANARTA = 'BTPN_SYARIAH'
    SAHABAT_SAMPOERNA = 'SAHABAT_SAMPOERNA'
    SINAR_HARAPAN_BALI = 'MANDIRI_TASPEN'
    SYARIAH_BUKOPIN = 'BUKOPIN_SYR'
    BTPN = 'TABUNGAN_PENSIUNAN_NASIONAL'
    VICTORIA = 'VICTORIA_INTERNASIONAL'
    VICTORIA_SYARIAH = 'VICTORIA_SYR'
    YUDHA_BHAKTI = 'YUDHA_BHAKTI'
    CENTRATAMA = 'CENTRATAMA'
    PRIMA_MASTER = 'PRIMA_MASTER'
    BPD_SULTRA = 'SULAWESI_TENGGARA'
    BPD_DIY = 'DAERAH_ISTIMEWA'
    BPD_KALTIM = 'KALIMANTAN_TIMUR'
    DKI = 'DKI'
    BPD_ACEH = 'ACEH'
    BPD_KALTENG = 'KALIMANTAN_TENGAH'
    BPD_JAMBI = 'JAMBI'
    BPD_SULSELBAR = 'SULSELBAR'
    BPD_LAMPUNG = 'LAMPUNG'
    BPD_RIAU_KEPRI = 'RIAU_DAN_KEPRI'
    BPD_SUMBAR = 'SUMATERA_BARAT'
    BJB = 'BJB'
    BPD_MALUKU = 'MALUKU'
    BPD_BENGKULU = 'BENGKULU'
    BPD_JATENG = 'JAWA_TENGAH'
    BPD_JATIM = 'JAWA_TIMUR'
    BPD_KALBAR = 'KALIMANTAN_BARAT'
    BPD_NTB = 'NUSA_TENGGARA_BARAT'
    BPD_NTT = 'NUSA_TENGGARA_TIMUR'
    BPD_SULTENG = 'SULAWESI'
    BPD_SULUT = 'SULUT'
    BPD_BALI = 'BALI'
    BPD_KALSEL = 'KALIMANTAN_SELATAN'
    BPD_PAPUA = 'PAPUA'
    BPD_SUMSEL_BABEL = 'SUMSEL_DAN_BABEL'
    BPD_SUMUT = 'SUMUT'
    COMMONWEALTH = 'COMMONWEALTH'
    AGRIS = 'AGRIS'
    ANZ = 'ANZ'
    BNP_PARIBAS = 'BNP_PARIBAS'
    CAPITAL = 'CAPITAL'
    DBS = 'DBS'
    MAYBANK_SYARIAH = 'MAYBANK_SYR'
    MIZUHO = 'MIZUHO'
    RABOBANK = 'RABOBANK'
    RESONA_PERDANIA = 'RESONA'
    WINDU_KENTJANA = 'CCB'
    WOORI = 'WOORI'
    CHINATRUST = 'CHINATRUST'
    SUMITOMO_MITSUI = 'MITSUI'
    AMERICA = 'BAML'
    BOC = 'BOC'
    CITIBANK = 'CITIBANK'
    DEUTSCHE = 'DEUTSCHE'
    JPMORGAN = 'JPMORGAN'
    STANDARD_CHARTERED = 'STANDARD_CHARTERED'
    BANGKOK = 'BANGKOK'
    TOKYO_MITSUBISHI = 'TOKYO'
    HSBC = 'HSBC'
    RBS = 'RBS'
    BPD_JAMBI_UUS = 'JAMBI_UUS'
    BPD_NTB_UUS = 'NUSA_TENGGARA_BARAT_UUS'
    BPD_RIAU_KEPRI_UUS = 'RIAU_DAN_KEPRI_UUS'
    BPD_SUMBAR_UUS = 'SUMATERA_BARAT_UUS'
    BPD_KALBAR_UUS = 'KALIMANTAN_BARAT_UUS'
    BPD_KALSEL_UUS = 'KALIMANTAN_SELATAN_UUS'
    BPD_KALTIM_UUS = 'KALIMANTAN_TIMUR_UUS'
    BPD_SUMSEL_BABEL_UUS = 'SUMSEL_DAN_BABEL_UUS'
    DKI_UUS = 'DKI_UUS'
    BPD_ACEH_UUS = 'ACEH_UUS'
    BPD_SUMUT_UUS = 'SUMUT_UUS'
    BPD_DIY_UUS = 'DAERAH_ISTIMEWA_UUS'
    BPD_JATENG_UUS = 'JAWA_TENGAH_UUS'
    BPD_JATIM_UUS = 'JAWA_TIMUR_UUS'
    BPD_SULSELBAR_UUS = 'SULSELBAR_UUS'
    HSBC_UUS = 'HSBC_UUS'
    EKSPOR = 'EXIMBANK'
    BTPN_UUS = 'BTPN_SYARIAH'
    BTN_UUS = 'BTN_UUS'
    CIMB_NIAGA_UUS = 'CIMB_UUS'
    OCBC_NISP_UUS = 'OCBC_UUS'
    DANAMON_UUS = 'DANAMON_UUS'
    PERMATA_UUS = 'PERMATA_UUS'

class XfersBankCode(object):
    BCA = 'BCA'
    BCA_SYARIAH = 'BCA_SYR'
    MANDIRI = 'MANDIRI'
    SYARIAH_MANDIRI = 'MANDIRI_SYR'
    BRI = 'BRI'
    SYARIAH_BRI = 'BRI_SYR'
    BNI = 'BNI'
    BNI_SYARIAH = 'BNI_SYR'
    CIMB_NIAGA = 'CIMB_NIAGA'
    DANAMON = 'DANAMON'
    PERMATA = 'PERMATA'
    PANIN = 'PANIN'
    PANIN_SYARIAH = 'PANIN_SYR'
    BTN = 'BTN'
    MEGA = 'MEGA'
    SYARIAH_MEGA = 'MEGA_SYR'
    ANTAR_DAERAH = 'ANTAR_DAERAH'
    ARTHA_GRAHA = 'ARTHA'
    BUKOPIN = 'BUKOPIN'
    BUMI_ARTA = 'BUMI_ARTA'
    EKONOMI = 'EKONOMI_RAHARJA'
    GANESHA = 'GANESHA'
    HANA = 'HANA'
    HIMPUNAN_SAUDARA = 'HIMPUNAN_SAUDARA'
    MNC = 'MNC_INTERNASIONAL'
    ICBC = 'ICBC'
    INDEX_SELINDO = 'INDEX_SELINDO'
    MAYBANK = 'BII'
    MASPION = 'MASPION'
    MAYAPADA = 'MAYAPADA'
    MESTIKA_DHARMA = 'MESTIKA_DHARMA'
    METRO_EXPRESS = 'SHINHAN'
    MUAMALAT = 'MUAMALAT'
    MUTIARA = 'JTRUST'
    NUSANTARA_PARAHYANGAN = 'NUSANTARA_PARAHYANGAN'
    OCBC_NISP = 'OCBC'
    INDIA = 'INDIA'
    AGRONIAGA = 'AGRONIAGA'
    SBI = 'SBI_INDONESIA'
    SINARMAS = 'SINARMAS'
    UOB = 'UOB'
    QNB_KESAWAN = 'QNB_INDONESIA'
    ANGLOMAS = 'ANGLOMAS'
    ANDARA = 'ANDARA'
    ARTOS = 'ARTOS'
    BISNIS = 'BISNIS_INTERNASIONAL'
    DINAR = 'DINAR_INDONESIA'
    FAMA = 'FAMA'
    HARDA = 'HARDA_INTERNASIONAL'
    INA_PERDANA = 'INA_PERDANA'
    BJB_SYARIAH = 'BJB_SYR'
    JASA_JAKARTA = 'JASA_JAKARTA'
    KESEJAHTERAAN_EKONOMI = 'KESEJAHTERAAN_EKONOMI'
    MAYORA = 'MAYORA'
    MITRA_NIAGA = 'MITRA_NIAGA'
    MULTI_ARTA_SENTOSA = 'MULTI_ARTA_SENTOSA'
    NATIONALNOBU = 'NATIONALNOBU'
    PUNDI = 'PUNDI_INDONESIA'
    ROYAL = 'ROYAL'
    SAHABAT_PURBA_DANARTA = 'SAHABAT_PURBA_DANARTA'
    SAHABAT_SAMPOERNA = 'SAHABAT_SAMPOERNA'
    SINAR_HARAPAN_BALI = 'MANDIRI_TASPEN'
    SYARIAH_BUKOPIN = 'BUKOPIN_SYR'
    BTPN = 'TABUNGAN_PENSIUNAN_NASIONAL'
    VICTORIA = 'VICTORIA_INTERNASIONAL'
    VICTORIA_SYARIAH = 'VICTORIA_SYR'
    YUDHA_BHAKTI = 'YUDHA_BHAKTI'
    CENTRATAMA = 'CENTRATAMA'
    PRIMA_MASTER = 'PRIMA_MASTER'
    BPD_SULTRA = 'SULAWESI_TENGGARA'
    BPD_DIY = 'BPD_DIY'
    BPD_KALTIM = 'KALIMANTAN_TIMUR'
    DKI = 'DKI'
    BPD_ACEH = 'ACEH'
    BPD_KALTENG = 'KALIMANTAN_TENGAH'
    BPD_JAMBI = 'JAMBI'
    BPD_SULSELBAR = 'SULSELBAR'
    BPD_LAMPUNG = 'LAMPUNG'
    BPD_RIAU_KEPRI = 'RIAU_DAN_KEPRI'
    BPD_SUMBAR = 'SUMATERA_BARAT'
    BJB = 'BJB'
    BPD_MALUKU = 'MALUKU'
    BPD_BENGKULU = 'BENGKULU'
    BPD_JATENG = 'JAWA_TENGAH'
    BPD_JATIM = 'JAWA_TIMUR'
    BPD_KALBAR = 'KALIMANTAN_BARAT'
    BPD_NTB = 'NUSA_TENGGARA_BARAT'
    BPD_NTT = 'NUSA_TENGGARA_TIMUR'
    BPD_SULTENG = 'SULAWESI'
    BPD_SULUT = 'SULUT'
    BPD_BALI = 'BALI'
    BPD_KALSEL = 'KALIMANTAN_SELATAN'
    BPD_PAPUA = 'PAPUA'
    BPD_SUMSEL_BABEL = 'SUMSEL_DAN_BABEL'
    BPD_SUMUT = 'SUMUT'
    COMMONWEALTH = 'COMMONWEALTH'
    AGRIS = 'AGRIS'
    ANZ = 'ANZ'
    BNP_PARIBAS = 'BNP'
    CAPITAL = 'CAPITAL'
    DBS = 'DBS'
    MAYBANK_SYARIAH = 'MAYBANK_SYR'
    MIZUHO = 'MIZUHO'
    RABOBANK = 'RABOBANK'
    RESONA_PERDANIA = 'RESONA'
    WINDU_KENTJANA = 'WINDU'
    WOORI = 'WOORI'
    CHINATRUST = 'CHINATRUST'
    SUMITOMO_MITSUI = 'MITSUI'
    AMERICA = 'BAML'
    BOC = 'BOC'
    CITIBANK = 'CITIBANK'
    DEUTSCHE = 'DEUTSCHE'
    JPMORGAN = 'JPMORGAN'
    STANDARD_CHARTERED = 'STANDARD_CHARTERED'
    BANGKOK = 'BANGKOK'
    TOKYO_MITSUBISHI = 'TOKYO'
    HSBC = 'HSBC'
    RBS = 'PRIMA_MASTER'
    BPD_JAMBI_UUS = 'JAMBI_UUS'
    BPD_NTB_UUS = 'NUSA_TENGGARA_BARAT_UUS'
    BPD_RIAU_KEPRI_UUS = 'RIAU_DAN_KEPRI_UUS'
    BPD_SUMBAR_UUS = 'SUMATERA_BARAT_UUS'
    BPD_KALBAR_UUS = 'KALIMANTAN_BARAT_UUS'
    BPD_KALSEL_UUS = 'KALIMANTAN_SELATAN_UUS'
    BPD_KALTIM_UUS = 'KALIMANTAN_TIMUR_UUS'
    BPD_SUMSEL_BABEL_UUS = 'SUMSEL_DAN_BABEL_UUS'
    DKI_UUS = 'DKI_UUS'
    BPD_ACEH_UUS = 'ACEH_UUS'
    BPD_SUMUT_UUS = 'SUMUT_UUS'
    BPD_DIY_UUS = 'BPD_DIY_SYR'
    BPD_JATENG_UUS = 'JAWA_TENGAH_UUS'
    BPD_JATIM_UUS = 'JAWA_TIMUR_UUS'
    BPD_SULSELBAR_UUS = 'SULSELBAR_UUS'
    HSBC_UUS = 'HSBC_UUS'
    EKSPOR = 'EKSPOR_INDONESIA'
    BTPN_UUS = 'TABUNGAN_PENSIUNAN_NASIONAL_UUS'
    BTN_UUS = 'BTN_UUS'
    CIMB_NIAGA_UUS = 'CIMB_UUS'
    OCBC_NISP_UUS = 'OCBC_UUS'
    DANAMON_UUS = 'DANAMON_UUS'
    PERMATA_UUS = 'PERMATA_UUS'


Bank = namedtuple(
    'Bank',
    [
        'bank_code',
        'bank_name',
        'min_account_number',
        'xendit_bank_code',
        'instamoney_bank_code',
        'xfers_bank_code',
        'swift_bank_code',
    ]
)

Banks = (

    Bank(
        bank_code=BankCodes.BCA,
        bank_name="BANK CENTRAL ASIA, Tbk (BCA)",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.BCA,
        instamoney_bank_code=InstamoneyBankCode.BCA,
        xfers_bank_code=XfersBankCode.BCA,
        swift_bank_code='CENAIDJA'
    ),
    Bank(
        bank_code=BankCodes.BCA_SYARIAH,
        bank_name="BANK BCA SYARIAH",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.BCA_SYARIAH,
        instamoney_bank_code=InstamoneyBankCode.BCA_SYARIAH,
        xfers_bank_code=XfersBankCode.BCA_SYARIAH,
        swift_bank_code='SYCAIDJ1'
    ),
    Bank(
        bank_code=BankCodes.MANDIRI,
        bank_name="BANK MANDIRI (PERSERO), Tbk",
        min_account_number=13,
        xendit_bank_code=XenditBankCode.MANDIRI,
        instamoney_bank_code=InstamoneyBankCode.MANDIRI,
        xfers_bank_code=XfersBankCode.MANDIRI,
        swift_bank_code='BMRIIDJA'
    ),
    Bank(
        bank_code=BankCodes.SYARIAH_MANDIRI,
        bank_name="BANK SYARIAH MANDIRI",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.SYARIAH_MANDIRI,
        instamoney_bank_code=InstamoneyBankCode.SYARIAH_MANDIRI,
        xfers_bank_code=XfersBankCode.SYARIAH_MANDIRI,
        swift_bank_code='BSMDIDJA'
    ),
    Bank(
        bank_code=BankCodes.BRI,
        bank_name="BANK RAKYAT INDONESIA (PERSERO), Tbk (BRI)",
        min_account_number=14,
        xendit_bank_code=XenditBankCode.BRI,
        instamoney_bank_code=InstamoneyBankCode.BRI,
        xfers_bank_code=XfersBankCode.BRI,
        swift_bank_code='BRINIDJA'
    ),
    Bank(
        bank_code=BankCodes.SYARIAH_BRI,
        bank_name="BANK BRI SYARIAH",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.SYARIAH_BRI,
        instamoney_bank_code=InstamoneyBankCode.SYARIAH_BRI,
        xfers_bank_code=XfersBankCode.SYARIAH_BRI,
        swift_bank_code='DJARIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BNI,
        bank_name="BANK NEGARA INDONESIA (PERSERO), Tbk (BNI)",
        min_account_number=9,
        xendit_bank_code=XenditBankCode.BNI,
        instamoney_bank_code=InstamoneyBankCode.BNI,
        xfers_bank_code=XfersBankCode.BNI,
        swift_bank_code='BNINIDJA'
    ),
    Bank(
        bank_code=BankCodes.BNI_SYARIAH,
        bank_name="BANK BNI SYARIAH",
        min_account_number=9,
        xendit_bank_code=XenditBankCode.BNI_SYARIAH,
        instamoney_bank_code=InstamoneyBankCode.BNI_SYARIAH,
        xfers_bank_code=XfersBankCode.BNI_SYARIAH,
        swift_bank_code='SYNIIDJ1'
    ),
    Bank(
        bank_code=BankCodes.CIMB_NIAGA,
        bank_name="BANK CIMB NIAGA, Tbk",
        min_account_number=12,
        xendit_bank_code=XenditBankCode.CIMB_NIAGA,
        instamoney_bank_code=InstamoneyBankCode.CIMB_NIAGA,
        xfers_bank_code=XfersBankCode.CIMB_NIAGA,
        swift_bank_code='BNIAIDJA'
    ),
    Bank(
        bank_code=BankCodes.DANAMON,
        bank_name="BANK DANAMON INDONESIA, Tbk",
        min_account_number=8,
        xendit_bank_code=XenditBankCode.DANAMON,
        instamoney_bank_code=InstamoneyBankCode.DANAMON,
        xfers_bank_code=XfersBankCode.DANAMON,
        swift_bank_code='BDINIDJA'
    ),
    Bank(
        bank_code=BankCodes.PERMATA,
        bank_name="BANK PERMATA, Tbk",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.PERMATA,
        instamoney_bank_code=InstamoneyBankCode.PERMATA,
        xfers_bank_code=XfersBankCode.PERMATA,
        swift_bank_code='BBBAIDJA'
    ),

    Bank(
        bank_code=BankCodes.PANIN,
        bank_name="PAN INDONESIA BANK, Tbk (Panin)",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.PANIN,
        instamoney_bank_code=InstamoneyBankCode.PANIN,
        xfers_bank_code=XfersBankCode.PANIN,
        swift_bank_code='PINBIDJA'
    ),
    Bank(
        bank_code=BankCodes.PANIN_SYARIAH,
        bank_name="BANK PANIN SYARIAH",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.PANIN_SYARIAH,
        instamoney_bank_code=InstamoneyBankCode.PANIN_SYARIAH,
        xfers_bank_code=XfersBankCode.PANIN_SYARIAH,
        swift_bank_code='ARFAIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BTN,
        bank_name="BANK TABUNGAN NEGARA (PERSERO) (BTN)",
        min_account_number=16,
        xendit_bank_code=XenditBankCode.BTN,
        instamoney_bank_code=InstamoneyBankCode.BTN,
        xfers_bank_code=XfersBankCode.BTN,
        swift_bank_code='BTANIDJA'
    ),
    Bank(
        bank_code=BankCodes.MEGA,
        bank_name="BANK MEGA, Tbk",
        min_account_number=15,
        xendit_bank_code=XenditBankCode.MEGA,
        instamoney_bank_code=InstamoneyBankCode.MEGA,
        xfers_bank_code=XfersBankCode.MEGA,
        swift_bank_code='MEGAIDJA'
    ),
    Bank(
        bank_code=BankCodes.SYARIAH_MEGA,
        bank_name="BANK MEGA SYARIAH",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.SYARIAH_MEGA,
        instamoney_bank_code=InstamoneyBankCode.SYARIAH_MEGA,
        xfers_bank_code=XfersBankCode.SYARIAH_MEGA,
        swift_bank_code='BUTGIDJ1'
    ),
    Bank(
        bank_code=BankCodes.ANTAR_DAERAH,
        bank_name="BANK CCB",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.ANTAR_DAERAH,
        instamoney_bank_code=InstamoneyBankCode.ANTAR_DAERAH,
        xfers_bank_code=XfersBankCode.ANTAR_DAERAH,
        swift_bank_code='MCORIDJA'
    ),
    Bank(
        bank_code=BankCodes.ARTHA_GRAHA,
        bank_name="BANK ARTHA GRAHA INTERNASIONAL, Tbk",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.ARTHA_GRAHA,
        instamoney_bank_code=InstamoneyBankCode.ARTHA_GRAHA,
        xfers_bank_code=XfersBankCode.ARTHA_GRAHA,
        swift_bank_code='ARTGIDJA'
    ),
    Bank(
        bank_code=BankCodes.BUKOPIN,
        bank_name="BANK BUKOPIN, Tbk",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.BUKOPIN,
        instamoney_bank_code=InstamoneyBankCode.BUKOPIN,
        xfers_bank_code=XfersBankCode.BUKOPIN,
        swift_bank_code='BBUKIDJA'
    ),
    Bank(
        bank_code=BankCodes.BUMI_ARTA,
        bank_name="BANK BUMI ARTA, Tbk",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.BUMI_ARTA,
        instamoney_bank_code=InstamoneyBankCode.BUMI_ARTA,
        xfers_bank_code=XfersBankCode.BUMI_ARTA,
        swift_bank_code='BBAIIDJA'
    ),
    Bank(
        bank_code=BankCodes.EKONOMI,
        bank_name="BANK HSBC",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.EKONOMI,
        instamoney_bank_code=InstamoneyBankCode.EKONOMI,
        xfers_bank_code=XfersBankCode.EKONOMI,
        swift_bank_code='EKONIDJA'
    ),
    Bank(
        bank_code=BankCodes.GANESHA,
        bank_name="BANK GANESHA",
        min_account_number=11,
        xendit_bank_code=XenditBankCode.GANESHA,
        instamoney_bank_code=InstamoneyBankCode.GANESHA,
        xfers_bank_code=XfersBankCode.GANESHA,
        swift_bank_code='GNESIDJA'
    ),
    Bank(
        bank_code=BankCodes.HANA,
        bank_name="BANK HANA",
        min_account_number=11,
        xendit_bank_code=XenditBankCode.HANA,
        instamoney_bank_code=InstamoneyBankCode.HANA,
        xfers_bank_code=XfersBankCode.HANA,
        swift_bank_code='HNBNIDJA'
    ),
    Bank(
        bank_code=BankCodes.HIMPUNAN_SAUDARA,
        bank_name="BANK HIMPUNAN SAUDARA 1906, Tbk",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.HIMPUNAN_SAUDARA,
        instamoney_bank_code=InstamoneyBankCode.HIMPUNAN_SAUDARA,
        xfers_bank_code=XfersBankCode.HIMPUNAN_SAUDARA,
        swift_bank_code='HVBKIDJA'
    ),
    Bank(
        bank_code=BankCodes.MNC,
        bank_name="BANK MNC INTERNASIONAL",
        min_account_number=15,
        xendit_bank_code=XenditBankCode.MNC,
        instamoney_bank_code=InstamoneyBankCode.MNC,
        xfers_bank_code=XfersBankCode.MNC,
        swift_bank_code='BUMIIDJA'
    ),
    Bank(
        bank_code=BankCodes.ICBC,
        bank_name="BANK ICBC INDONESIA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.ICBC,
        instamoney_bank_code=InstamoneyBankCode.ICBC,
        xfers_bank_code=XfersBankCode.ICBC,
        swift_bank_code='ICBKIDJA'
    ),
    Bank(
        bank_code=BankCodes.INDEX_SELINDO,
        bank_name="BANK INDEX SELINDO",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.INDEX_SELINDO,
        instamoney_bank_code=InstamoneyBankCode.INDEX_SELINDO,
        xfers_bank_code=XfersBankCode.INDEX_SELINDO,
        swift_bank_code='BIDXIDJA'
    ),
    Bank(
        bank_code=BankCodes.MAYBANK,
        bank_name="BANK MAYBANK",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.MAYBANK,
        instamoney_bank_code=InstamoneyBankCode.MAYBANK,
        xfers_bank_code=XfersBankCode.MAYBANK,
        swift_bank_code='IBBKIDJA'
    ),
    Bank(
        bank_code=BankCodes.MASPION,
        bank_name="BANK MASPION INDONESIA",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.MASPION,
        instamoney_bank_code=InstamoneyBankCode.MASPION,
        xfers_bank_code=XfersBankCode.MASPION,
        swift_bank_code='MASDIDJS'
    ),
    Bank(
        bank_code=BankCodes.MAYAPADA,
        bank_name="BANK MAYAPADA INTERNATIONAL, Tbk",
        min_account_number=11,
        xendit_bank_code=XenditBankCode.MAYAPADA,
        instamoney_bank_code=InstamoneyBankCode.MAYAPADA,
        xfers_bank_code=XfersBankCode.MAYAPADA,
        swift_bank_code='MAYAIDJA'
    ),
    Bank(
        bank_code=BankCodes.MESTIKA_DHARMA,
        bank_name="BANK MESTIKA DHARMA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.MESTIKA_DHARMA,
        instamoney_bank_code=InstamoneyBankCode.MESTIKA_DHARMA,
        xfers_bank_code=XfersBankCode.MESTIKA_DHARMA,
        swift_bank_code='MEDHIDS1'
    ),
    Bank(
        bank_code=BankCodes.METRO_EXPRESS,
        bank_name="BANK SHINHAN",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.METRO_EXPRESS,
        instamoney_bank_code=InstamoneyBankCode.METRO_EXPRESS,
        xfers_bank_code=XfersBankCode.METRO_EXPRESS,
        swift_bank_code='MEEKIDJ1'
    ),
    Bank(
        bank_code=BankCodes.MUAMALAT,
        bank_name="BANK MUAMALAT INDONESIA",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.MUAMALAT,
        instamoney_bank_code=InstamoneyBankCode.MUAMALAT,
        xfers_bank_code=XfersBankCode.MUAMALAT,
        swift_bank_code='MUABIDJA'
    ),
    Bank(
        bank_code=BankCodes.MUTIARA,
        bank_name="BANK JTRUST",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.MUTIARA,
        instamoney_bank_code=InstamoneyBankCode.MUTIARA,
        # swift_bank_code=''  # does not exist yet
        xfers_bank_code=XfersBankCode.MUTIARA,
        swift_bank_code='CICTIDJA'  # does not exist yet
    ),
    Bank(
        bank_code=BankCodes.NUSANTARA_PARAHYANGAN,
        bank_name="BANK NUSANTARA PARAHYANGAN,Tbk",
        min_account_number=11,
        xendit_bank_code=XenditBankCode.NUSANTARA_PARAHYANGAN,
        instamoney_bank_code=InstamoneyBankCode.NUSANTARA_PARAHYANGAN,
        xfers_bank_code=XfersBankCode.NUSANTARA_PARAHYANGAN,
        swift_bank_code='NUPAIDJ6'
    ),
    Bank(
        bank_code=BankCodes.OCBC_NISP,
        bank_name="BANK OCBC NISP, Tbk",
        min_account_number=12,
        xendit_bank_code=XenditBankCode.OCBC_NISP,
        instamoney_bank_code=InstamoneyBankCode.OCBC_NISP,
        xfers_bank_code=XfersBankCode.OCBC_NISP,
        swift_bank_code='NISPIDJA'
    ),
    Bank(
        bank_code=BankCodes.INDIA,
        bank_name="BANK OF INDIA INDONESIA, Tbk",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.INDIA,
        instamoney_bank_code=InstamoneyBankCode.INDIA,
        xfers_bank_code=XfersBankCode.INDIA,
        swift_bank_code='BKIDIDJA'
    ),
    Bank(
        bank_code=BankCodes.AGRONIAGA,
        bank_name="BANK RAKYAT INDONESIA AGRONIAGA, Tbk",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.AGRONIAGA,
        instamoney_bank_code=InstamoneyBankCode.AGRONIAGA,
        xfers_bank_code=XfersBankCode.AGRONIAGA,
        swift_bank_code='AGTBIDJA'
    ),
    Bank(
        bank_code=BankCodes.SBI,
        bank_name="BANK SBI INDONESIA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.SBI,
        instamoney_bank_code=InstamoneyBankCode.SBI,
        xfers_bank_code=XfersBankCode.SBI,
        swift_bank_code='IDMOIDJ1'
    ),
    Bank(
        bank_code=BankCodes.SINARMAS,
        bank_name="BANK SINARMAS, Tbk",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.SINARMAS,
        instamoney_bank_code=InstamoneyBankCode.SINARMAS,
        xfers_bank_code=XfersBankCode.SINARMAS,
        swift_bank_code='SBJKIDJA'
    ),
    Bank(
        bank_code=BankCodes.UOB,
        bank_name="BANK UOB INDONESIA (dahulu UOB Buana)",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.UOB,
        instamoney_bank_code=InstamoneyBankCode.UOB,
        xfers_bank_code=XfersBankCode.UOB,
        swift_bank_code='BBIJIDJA'
    ),
    Bank(
        bank_code=BankCodes.QNB_KESAWAN,
        bank_name="QNB BANK INDONESIA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.QNB_KESAWAN,
        instamoney_bank_code=InstamoneyBankCode.QNB_KESAWAN,
        xfers_bank_code=XfersBankCode.QNB_KESAWAN,
        swift_bank_code='AWANIDJA'
    ),
    Bank(
        bank_code=BankCodes.ANGLOMAS,
        bank_name="ANGLOMAS INTERNASIONAL BANK",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.ANGLOMAS,
        instamoney_bank_code=InstamoneyBankCode.ANGLOMAS,
        xfers_bank_code=XfersBankCode.ANGLOMAS,
        swift_bank_code='LOMAIDJ1'
    ),
    Bank(
        bank_code=BankCodes.ANDARA,
        bank_name="BANK ANDARA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.ANDARA,
        instamoney_bank_code=InstamoneyBankCode.ANDARA,
        xfers_bank_code=XfersBankCode.ANDARA,
        swift_bank_code='RIPAIDJ1'
    ),
    Bank(
        bank_code=BankCodes.ARTOS,
        bank_name="BANK ARTOS INDONESIA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.ARTOS,
        instamoney_bank_code=InstamoneyBankCode.ARTOS,
        xfers_bank_code=XfersBankCode.ARTOS,
        swift_bank_code='ATOSIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BISNIS,
        bank_name="BANK BISNIS INTERNASIONAL",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BISNIS,
        instamoney_bank_code=InstamoneyBankCode.BISNIS,
        xfers_bank_code=XfersBankCode.BISNIS,
        swift_bank_code='BUSTIDJ1'
    ),
    Bank(
        bank_code=BankCodes.DINAR,
        bank_name="BANK DINAR INDONESIA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.DINAR,
        instamoney_bank_code=InstamoneyBankCode.DINAR,
        xfers_bank_code=XfersBankCode.DINAR,
        swift_bank_code='LMANIDJ1'
    ),
    Bank(
        bank_code=BankCodes.FAMA,
        bank_name="BANK FAMA INTERNASIONAL",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.FAMA,
        instamoney_bank_code=InstamoneyBankCode.FAMA,
        xfers_bank_code=XfersBankCode.FAMA,
        swift_bank_code='FAMAIDJ1'
    ),
    Bank(
        bank_code=BankCodes.HARDA,
        bank_name="BANK HARDA INTERNASIONAL",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.HARDA,
        instamoney_bank_code=InstamoneyBankCode.HARDA,
        xfers_bank_code=XfersBankCode.HARDA,
        swift_bank_code='HRDAIDJ1'
    ),
    Bank(
        bank_code=BankCodes.INA_PERDANA,
        bank_name="BANK INA PERDANA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.INA_PERDANA,
        instamoney_bank_code=InstamoneyBankCode.INA_PERDANA,
        xfers_bank_code=XfersBankCode.INA_PERDANA,
        swift_bank_code='INPBIDJ1'
    ),

    Bank(
        bank_code=BankCodes.BJB_SYARIAH,
        bank_name="BANK JABAR BANTEN SYARIAH",
        min_account_number=13,
        xendit_bank_code=XenditBankCode.BJB_SYARIAH,
        instamoney_bank_code=InstamoneyBankCode.BJB_SYARIAH,
        xfers_bank_code=XfersBankCode.BJB_SYARIAH,
        swift_bank_code='SYJBIDJ1'
    ),
    Bank(
        bank_code=BankCodes.JASA_JAKARTA,
        bank_name="BANK JASA JAKARTA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.JASA_JAKARTA,
        instamoney_bank_code=InstamoneyBankCode.JASA_JAKARTA,
        xfers_bank_code=XfersBankCode.JASA_JAKARTA,
        swift_bank_code='JAJSIDJ1'
    ),
    Bank(
        bank_code=BankCodes.KESEJAHTERAAN_EKONOMI,
        bank_name="BANK KESEJAHTERAAN EKONOMI",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.KESEJAHTERAAN_EKONOMI,
        instamoney_bank_code=InstamoneyBankCode.KESEJAHTERAAN_EKONOMI,
        xfers_bank_code=XfersBankCode.KESEJAHTERAAN_EKONOMI,
        swift_bank_code='KSEBIDJ1'
    ),
    Bank(
        bank_code=BankCodes.MAYORA,
        bank_name="BANK MAYORA",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.MAYORA,
        instamoney_bank_code=InstamoneyBankCode.MAYORA,
        xfers_bank_code=XfersBankCode.MAYORA,
        swift_bank_code='MAYOIDJA'
    ),
    Bank(
        bank_code=BankCodes.MITRA_NIAGA,
        bank_name="BANK MITRANIAGA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.MITRA_NIAGA,
        instamoney_bank_code=InstamoneyBankCode.MITRA_NIAGA,
        xfers_bank_code=XfersBankCode.MITRA_NIAGA,
        swift_bank_code='MGABIDJ1'
    ),
    Bank(
        bank_code=BankCodes.MULTI_ARTA_SENTOSA,
        bank_name="BANK MULTIARTA SENTOSA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.MULTI_ARTA_SENTOSA,
        instamoney_bank_code=InstamoneyBankCode.MULTI_ARTA_SENTOSA,
        xfers_bank_code=XfersBankCode.MULTI_ARTA_SENTOSA,
        swift_bank_code='BMSEIDJA'
    ),
    Bank(
        bank_code=BankCodes.NATIONALNOBU,
        bank_name="BANK NATIONALNOBU",
        min_account_number=11,
        xendit_bank_code=XenditBankCode.NATIONALNOBU,
        instamoney_bank_code=InstamoneyBankCode.NATIONALNOBU,
        xfers_bank_code=XfersBankCode.NATIONALNOBU,
        swift_bank_code='LFIBIDJ1'
    ),
    Bank(
        bank_code=BankCodes.PUNDI,
        bank_name="BANK PUNDI BANTEN",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.PUNDI,
        instamoney_bank_code=InstamoneyBankCode.PUNDI,
        xfers_bank_code=XfersBankCode.PUNDI,
        swift_bank_code='PDBBIDJ1'
    ),
    Bank(
        bank_code=BankCodes.ROYAL,
        bank_name="BANK ROYAL INDONESIA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.ROYAL,
        instamoney_bank_code=InstamoneyBankCode.ROYAL,
        xfers_bank_code=XfersBankCode.ROYAL,
        swift_bank_code='ROYBIDJ1'
    ),
    Bank(
        bank_code=BankCodes.SAHABAT_PURBA_DANARTA,
        bank_name="BANK BTPN SYARIAH",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.SAHABAT_PURBA_DANARTA,
        instamoney_bank_code=InstamoneyBankCode.SAHABAT_PURBA_DANARTA,
        xfers_bank_code=XfersBankCode.SAHABAT_PURBA_DANARTA,
        swift_bank_code='PUBAIDJ1'
    ),
    Bank(
        bank_code=BankCodes.SAHABAT_SAMPOERNA,
        bank_name="BANK SAHABAT SAMPOERNA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.SAHABAT_SAMPOERNA,
        instamoney_bank_code=InstamoneyBankCode.SAHABAT_SAMPOERNA,
        xfers_bank_code=XfersBankCode.SAHABAT_SAMPOERNA,
        swift_bank_code='BDIPIDJ1'
    ),
    Bank(
        bank_code=BankCodes.SINAR_HARAPAN_BALI,
        bank_name="BANK MANDIRI TASPEN",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.SINAR_HARAPAN_BALI,
        instamoney_bank_code=InstamoneyBankCode.SINAR_HARAPAN_BALI,
        xfers_bank_code=XfersBankCode.SINAR_HARAPAN_BALI,
        swift_bank_code='SIHBIDJ1'
    ),
    Bank(
        bank_code=BankCodes.SYARIAH_BUKOPIN,
        bank_name="BANK SYARIAH BUKOPIN",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.SYARIAH_BUKOPIN,
        instamoney_bank_code=InstamoneyBankCode.SYARIAH_BUKOPIN,
        xfers_bank_code=XfersBankCode.SYARIAH_BUKOPIN,
        swift_bank_code='SDOBIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BTPN,
        bank_name="BANK TABUNGAN PENSIUNAN NASIONAL, Tbk (BTPN)",
        min_account_number=11,
        xendit_bank_code=XenditBankCode.BTPN,
        instamoney_bank_code=InstamoneyBankCode.BTPN,
        xfers_bank_code=XfersBankCode.BTPN,
        swift_bank_code='BTPNIDJA'
    ),
    Bank(
        bank_code=BankCodes.VICTORIA,
        bank_name="BANK VICTORIA INTERNATIONAL, Tbk",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.VICTORIA,
        instamoney_bank_code=InstamoneyBankCode.VICTORIA,
        xfers_bank_code=XfersBankCode.VICTORIA,
        swift_bank_code='BVICIDJA'
    ),
    Bank(
        bank_code=BankCodes.VICTORIA_SYARIAH,
        bank_name="BANK VICTORIA SYARIAH",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.VICTORIA_SYARIAH,
        instamoney_bank_code=InstamoneyBankCode.VICTORIA_SYARIAH,
        xfers_bank_code=XfersBankCode.VICTORIA_SYARIAH,
        swift_bank_code='SWAGIDJ1'
    ),
    Bank(
        bank_code=BankCodes.YUDHA_BHAKTI,
        bank_name="BANK YUDHA BHAKTI",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.YUDHA_BHAKTI,
        instamoney_bank_code=InstamoneyBankCode.YUDHA_BHAKTI,
        xfers_bank_code=XfersBankCode.YUDHA_BHAKTI,
        swift_bank_code='YUDBIDJ1'
    ),
    Bank(
        bank_code=BankCodes.CENTRATAMA,
        bank_name="CENTRATAMA NASIONAL BANK",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.CENTRATAMA,
        instamoney_bank_code=InstamoneyBankCode.CENTRATAMA,
        xfers_bank_code=XfersBankCode.CENTRATAMA,
        swift_bank_code='CNBAIDJ1'
    ),
    Bank(
        bank_code=BankCodes.PRIMA_MASTER,
        bank_name="PRIMA MASTER BANK",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.PRIMA_MASTER,
        instamoney_bank_code=InstamoneyBankCode.PRIMA_MASTER,
        xfers_bank_code=XfersBankCode.PRIMA_MASTER,
        swift_bank_code='PMASIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_SULTRA,
        bank_name="BPD SULAWESI TENGGARA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_SULTRA,
        instamoney_bank_code=InstamoneyBankCode.BPD_SULTRA,
        xfers_bank_code=XfersBankCode.BPD_SULTRA,
        swift_bank_code='PDWRIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_DIY,
        bank_name="BPD YOGYAKARTA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_DIY,
        instamoney_bank_code=InstamoneyBankCode.BPD_DIY,
        xfers_bank_code=XfersBankCode.BPD_DIY,
        swift_bank_code='PDYKIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_KALTIM,
        bank_name="BPD KALIMANTAN TIMUR",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.BPD_KALTIM,
        instamoney_bank_code=InstamoneyBankCode.BPD_KALTIM,
        xfers_bank_code=XfersBankCode.BPD_KALTIM,
        swift_bank_code='PDKTIDJ1'
    ),
    Bank(
        bank_code=BankCodes.DKI,
        bank_name="BANK DKI",
        min_account_number=11,
        xendit_bank_code=XenditBankCode.DKI,
        instamoney_bank_code=InstamoneyBankCode.DKI,
        xfers_bank_code=XfersBankCode.DKI,
        swift_bank_code='BDKIIDJA'
    ),
    Bank(
        bank_code=BankCodes.BPD_ACEH,
        bank_name="BANK ACEH",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_ACEH,
        instamoney_bank_code=InstamoneyBankCode.BPD_ACEH,
        xfers_bank_code=XfersBankCode.BPD_ACEH,
        swift_bank_code='PDACIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_KALTENG,
        bank_name="BANK KALIMANTAN TENGAH",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_KALTENG,
        instamoney_bank_code=InstamoneyBankCode.BPD_KALTENG,
        xfers_bank_code=XfersBankCode.BPD_KALTENG,
        swift_bank_code='PDKGIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_JAMBI,
        bank_name="BPD JAMBI",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_JAMBI,
        instamoney_bank_code=InstamoneyBankCode.BPD_JAMBI,
        xfers_bank_code=XfersBankCode.BPD_JAMBI,
        swift_bank_code='PDJMIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_SULSELBAR,
        bank_name="BPD SULAWESI SELATAN DAN SULAWESI BARAT",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_SULSELBAR,
        instamoney_bank_code=InstamoneyBankCode.BPD_SULSELBAR,
        xfers_bank_code=XfersBankCode.BPD_SULSELBAR,
        swift_bank_code='PDWSIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_LAMPUNG,
        bank_name="BPD LAMPUNG",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_LAMPUNG,
        instamoney_bank_code=InstamoneyBankCode.BPD_LAMPUNG,
        xfers_bank_code=XfersBankCode.BPD_LAMPUNG,
        swift_bank_code='PDLPIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_RIAU_KEPRI,
        bank_name="BPD RIAU KEPRI",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.BPD_RIAU_KEPRI,
        instamoney_bank_code=InstamoneyBankCode.BPD_RIAU_KEPRI,
        xfers_bank_code=XfersBankCode.BPD_RIAU_KEPRI,
        swift_bank_code='PDRIIDJA'
    ),
    Bank(
        bank_code=BankCodes.BPD_SUMBAR,
        bank_name="BPD SUMATERA BARAT",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_SUMBAR,
        instamoney_bank_code=InstamoneyBankCode.BPD_SUMBAR,
        xfers_bank_code=XfersBankCode.BPD_SUMBAR,
        swift_bank_code='PDSBIDSP'
    ),
    Bank(
        bank_code=BankCodes.BJB,
        bank_name="BPD JAWA BARAT DAN BANTEN, Tbk",
        min_account_number=13,
        xendit_bank_code=XenditBankCode.BJB,
        instamoney_bank_code=InstamoneyBankCode.BJB,
        xfers_bank_code=XfersBankCode.BJB,
        swift_bank_code='PDJBIDJA'
    ),

    Bank(
        bank_code=BankCodes.BPD_MALUKU,
        bank_name="BPD MALUKU",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_MALUKU,
        instamoney_bank_code=InstamoneyBankCode.BPD_MALUKU,
        xfers_bank_code=XfersBankCode.BPD_MALUKU,
        swift_bank_code='PDMLIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_BENGKULU,
        bank_name="BPD BENGKULU",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_BENGKULU,
        instamoney_bank_code=InstamoneyBankCode.BPD_BENGKULU,
        xfers_bank_code=XfersBankCode.BPD_BENGKULU,
        swift_bank_code='PDBKIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_JATENG,
        bank_name="BPD JAWA TENGAH",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_JATENG,
        instamoney_bank_code=InstamoneyBankCode.BPD_JATENG,
        xfers_bank_code=XfersBankCode.BPD_JATENG,
        swift_bank_code='PDJGIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_JATIM,
        bank_name="BPD JAWA TIMUR",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.BPD_JATIM,
        instamoney_bank_code=InstamoneyBankCode.BPD_JATIM,
        xfers_bank_code=XfersBankCode.BPD_JATIM,
        swift_bank_code='PDJTIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_KALBAR,
        bank_name="BPD KALIMANTAN BARAT",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_KALBAR,
        instamoney_bank_code=InstamoneyBankCode.BPD_KALBAR,
        xfers_bank_code=XfersBankCode.BPD_KALBAR,
        swift_bank_code='PDKBIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_NTB,
        bank_name="BPD NUSA TENGGARA BARAT",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_NTB,
        instamoney_bank_code=InstamoneyBankCode.BPD_NTB,
        xfers_bank_code=XfersBankCode.BPD_NTB,
        swift_bank_code='PDNBIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_NTT,
        bank_name="BPD NUSA TENGGARA TIMUR",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_NTT,
        instamoney_bank_code=InstamoneyBankCode.BPD_NTT,
        xfers_bank_code=XfersBankCode.BPD_NTT,
        swift_bank_code='PDNTIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_SULTENG,
        bank_name="BPD SULAWESI",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_SULTENG,
        instamoney_bank_code=InstamoneyBankCode.BPD_SULTENG,
        xfers_bank_code=XfersBankCode.BPD_SULTENG,
        swift_bank_code='PDWGIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_SULUT,
        bank_name="BPD SULUT",
        min_account_number=14,
        xendit_bank_code=XenditBankCode.BPD_SULUT,
        instamoney_bank_code=InstamoneyBankCode.BPD_SULUT,
        xfers_bank_code=XfersBankCode.BPD_SULUT,
        swift_bank_code='PDWUIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_BALI,
        bank_name="BPD BALI",
        min_account_number=13,
        xendit_bank_code=XenditBankCode.BPD_BALI,
        instamoney_bank_code=InstamoneyBankCode.BPD_BALI,
        xfers_bank_code=XfersBankCode.BPD_BALI,
        swift_bank_code='ABALIDBS'
    ),
    Bank(
        bank_code=BankCodes.BPD_KALSEL,
        bank_name="BPD KALIMANTAN SELATAN",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_KALSEL,
        instamoney_bank_code=InstamoneyBankCode.BPD_KALSEL,
        xfers_bank_code=XfersBankCode.BPD_KALSEL,
        swift_bank_code='PDKSIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_PAPUA,
        bank_name="BPD PAPUA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_PAPUA,
        instamoney_bank_code=InstamoneyBankCode.BPD_PAPUA,
        xfers_bank_code=XfersBankCode.BPD_PAPUA,
        swift_bank_code='PDIJIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_SUMSEL_BABEL,
        bank_name="BPD SUMATERA SELATAN DAN BANGKA BELITUNG",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_SUMSEL_BABEL,
        instamoney_bank_code=InstamoneyBankCode.BPD_SUMSEL_BABEL,
        xfers_bank_code=XfersBankCode.BPD_SUMSEL_BABEL,
        swift_bank_code='BSSPIDSP'
    ),
    Bank(
        bank_code=BankCodes.BPD_SUMUT,
        bank_name="BPD SUMATERA UTARA",
        min_account_number=14,
        xendit_bank_code=XenditBankCode.BPD_SUMUT,
        instamoney_bank_code=InstamoneyBankCode.BPD_SUMUT,
        xfers_bank_code=XfersBankCode.BPD_SUMUT,
        swift_bank_code='PDSUIDJ1'
    ),
    Bank(
        bank_code=BankCodes.COMMONWEALTH,
        bank_name="BANK COMMONWEALTH",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.COMMONWEALTH,
        instamoney_bank_code=InstamoneyBankCode.COMMONWEALTH,
        xfers_bank_code=XfersBankCode.COMMONWEALTH,
        swift_bank_code='BICNIDJA'
    ),
    Bank(
        bank_code=BankCodes.AGRIS,
        bank_name="BANK AGRIS",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.AGRIS,
        instamoney_bank_code=InstamoneyBankCode.AGRIS,
        xfers_bank_code=XfersBankCode.AGRIS,
        swift_bank_code='AGSSIDJA'
    ),
    Bank(
        bank_code=BankCodes.ANZ,
        bank_name="BANK ANZ INDONESIA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.ANZ,
        instamoney_bank_code=InstamoneyBankCode.ANZ,
        xfers_bank_code=XfersBankCode.ANZ,
        swift_bank_code='ANZBIDJX'
    ),
    Bank(
        bank_code=BankCodes.BNP_PARIBAS,
        bank_name="BANK BNP PARIBAS INDONESIA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BNP_PARIBAS,
        instamoney_bank_code=InstamoneyBankCode.BNP_PARIBAS,
        xfers_bank_code=XfersBankCode.BNP_PARIBAS,
        swift_bank_code='BNPAIDJA'
    ),
    Bank(
        bank_code=BankCodes.CAPITAL,
        bank_name="BANK CAPITAL INDONESIA, Tbk",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.CAPITAL,
        instamoney_bank_code=InstamoneyBankCode.CAPITAL,
        xfers_bank_code=XfersBankCode.CAPITAL,
        swift_bank_code='BCIAIDJA'
    ),
    Bank(
        bank_code=BankCodes.DBS,
        bank_name="BANK DBS INDONESIA",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.DBS,
        instamoney_bank_code=InstamoneyBankCode.DBS,
        xfers_bank_code=XfersBankCode.DBS,
        swift_bank_code='DBSBIDJA'
    ),
    Bank(
        bank_code=BankCodes.MAYBANK_SYARIAH,
        bank_name="BANK MAYBANK SYARIAH INDONESIA",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.MAYBANK_SYARIAH,
        instamoney_bank_code=InstamoneyBankCode.MAYBANK_SYARIAH,
        xfers_bank_code=XfersBankCode.MAYBANK_SYARIAH,
        swift_bank_code='MBBEIDJA'
    ),
    Bank(
        bank_code=BankCodes.MIZUHO,
        bank_name="BANK MIZUHO INDONESIA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.MIZUHO,
        instamoney_bank_code=InstamoneyBankCode.MIZUHO,
        xfers_bank_code=XfersBankCode.MIZUHO,
        swift_bank_code='MHCCIDJA'
    ),
    Bank(
        bank_code=BankCodes.RABOBANK,
        bank_name="BANK RABOBANK INTERNATIONAL INDONESIA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.RABOBANK,
        instamoney_bank_code=InstamoneyBankCode.RABOBANK,
        xfers_bank_code=XfersBankCode.RABOBANK,
        swift_bank_code='RABOIDJA'
    ),
    Bank(
        bank_code=BankCodes.RESONA_PERDANIA,
        bank_name="BANK RESONA PERDANIA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.RESONA_PERDANIA,
        instamoney_bank_code=InstamoneyBankCode.RESONA_PERDANIA,
        xfers_bank_code=XfersBankCode.RESONA_PERDANIA,
        swift_bank_code='BPIAIDJA'
    ),
    Bank(
        bank_code=BankCodes.WINDU_KENTJANA,
        bank_name="BANK CCB",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.WINDU_KENTJANA,
        instamoney_bank_code=InstamoneyBankCode.WINDU_KENTJANA,
        xfers_bank_code=XfersBankCode.WINDU_KENTJANA,
        swift_bank_code='BWKIIDJA'
    ),
    Bank(
        bank_code=BankCodes.WOORI,
        bank_name="BANK WOORI INDONESIA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.WOORI,
        instamoney_bank_code=InstamoneyBankCode.WOORI,
        xfers_bank_code=XfersBankCode.WOORI,
        swift_bank_code='HVBKIDJA'
    ),
    Bank(
        bank_code=BankCodes.CHINATRUST,
        bank_name="BANK CHINATRUST INDONESIA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.CHINATRUST,
        instamoney_bank_code=InstamoneyBankCode.CHINATRUST,
        xfers_bank_code=XfersBankCode.CHINATRUST,
        swift_bank_code='CTCBIDJA'
    ),
    Bank(
        bank_code=BankCodes.SUMITOMO_MITSUI,
        bank_name="BANK SUMITOMO MITSUI INDONESIA",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.SUMITOMO_MITSUI,
        instamoney_bank_code=InstamoneyBankCode.SUMITOMO_MITSUI,
        xfers_bank_code=XfersBankCode.SUMITOMO_MITSUI,
        swift_bank_code='SUNIIDJA'
    ),
    Bank(
        bank_code=BankCodes.AMERICA,
        bank_name="BANK OF AMERICA, N.A",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.AMERICA,
        instamoney_bank_code=InstamoneyBankCode.AMERICA,
        xfers_bank_code=XfersBankCode.AMERICA,
        swift_bank_code='BOFAID2X'
    ),
    Bank(
        bank_code=BankCodes.BOC,
        bank_name="BANK OF CHINA LIMITED",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BOC,
        instamoney_bank_code=InstamoneyBankCode.BOC,
        xfers_bank_code=XfersBankCode.BOC,
        swift_bank_code='BKCHIDJA'
    ),
    Bank(
        bank_code=BankCodes.CITIBANK,
        bank_name="CITIBANK N.A.",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.CITIBANK,
        instamoney_bank_code=InstamoneyBankCode.CITIBANK,
        xfers_bank_code=XfersBankCode.CITIBANK,
        swift_bank_code='CITIIDJX'
    ),
    Bank(
        bank_code=BankCodes.DEUTSCHE,
        bank_name="DEUTSCHE BANK AG.",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.DEUTSCHE,
        instamoney_bank_code=InstamoneyBankCode.DEUTSCHE,
        xfers_bank_code=XfersBankCode.DEUTSCHE,
        swift_bank_code='DEUTIDJA'
    ),
    Bank(
        bank_code=BankCodes.JPMORGAN,
        bank_name="JP. MORGAN CHASE BANK, N.A.",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.JPMORGAN,
        instamoney_bank_code=InstamoneyBankCode.JPMORGAN,
        xfers_bank_code=XfersBankCode.JPMORGAN,
        swift_bank_code='CHASIDJX'
    ),
    Bank(
        bank_code=BankCodes.STANDARD_CHARTERED,
        bank_name="STANDARD CHARTERED BANK",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.STANDARD_CHARTERED,
        instamoney_bank_code=InstamoneyBankCode.STANDARD_CHARTERED,
        xfers_bank_code=XfersBankCode.STANDARD_CHARTERED,
        swift_bank_code='SCBLIDJX'
    ),
    Bank(
        bank_code=BankCodes.BANGKOK,
        bank_name="THE BANGKOK BANK COMP. LTD",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BANGKOK,
        instamoney_bank_code=InstamoneyBankCode.BANGKOK,
        xfers_bank_code=XfersBankCode.BANGKOK,
        swift_bank_code='BKKBIDJA'
    ),
    Bank(
        bank_code=BankCodes.TOKYO_MITSUBISHI,
        bank_name="THE BANK OF TOKYO MITSUBISHI UFJ LTD",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.TOKYO_MITSUBISHI,
        instamoney_bank_code=InstamoneyBankCode.TOKYO_MITSUBISHI,
        xfers_bank_code=XfersBankCode.TOKYO_MITSUBISHI,
        swift_bank_code='BOTKIDJX'
    ),
    Bank(
        bank_code=BankCodes.HSBC,
        bank_name="THE HONGKONG & SHANGHAI BANKING CORP",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.HSBC,
        instamoney_bank_code=InstamoneyBankCode.HSBC,
        xfers_bank_code=XfersBankCode.HSBC,
        swift_bank_code='HSBCIDJA'
    ),
    Bank(
        bank_code=BankCodes.RBS,
        bank_name="THE ROYAL BANK OF SCOTLAND N.V.",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.RBS,
        instamoney_bank_code=InstamoneyBankCode.RBS,
        xfers_bank_code=XfersBankCode.RBS,
        swift_bank_code='ABNAIDJA'
    ),
    Bank(
        bank_code=BankCodes.BPD_JAMBI_UUS,
        bank_name="BPD JAMBI UUS (Unit Usaha Syariah)",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_JAMBI_UUS,
        instamoney_bank_code=InstamoneyBankCode.BPD_JAMBI_UUS,
        xfers_bank_code=XfersBankCode.BPD_JAMBI_UUS,
        swift_bank_code='SYJMIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_NTB_UUS,
        bank_name="BPD NUSA TENGGARA BARAT UUS (Unit Usaha Syariah)",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_NTB_UUS,
        instamoney_bank_code=InstamoneyBankCode.BPD_NTB_UUS,
        xfers_bank_code=XfersBankCode.BPD_NTB_UUS,
        swift_bank_code='SYNBIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_RIAU_KEPRI_UUS,
        bank_name="BPD RIAU KEPRI UUS (Unit Usaha Syariah)",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.BPD_RIAU_KEPRI_UUS,
        instamoney_bank_code=InstamoneyBankCode.BPD_RIAU_KEPRI_UUS,
        xfers_bank_code=XfersBankCode.BPD_RIAU_KEPRI_UUS,
        swift_bank_code='SYRIIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_SUMBAR_UUS,
        bank_name="BPD SUMATERA BARAT UUS (Unit Usaha Syariah)",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_SUMBAR_UUS,
        instamoney_bank_code=InstamoneyBankCode.BPD_SUMBAR_UUS,
        xfers_bank_code=XfersBankCode.BPD_SUMBAR_UUS,
        swift_bank_code='SYSBIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_KALBAR_UUS,
        bank_name="BPD KALIMANTAN BARAT UUS (Unit Usaha Syariah)",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_KALBAR_UUS,
        instamoney_bank_code=InstamoneyBankCode.BPD_KALBAR_UUS,
        xfers_bank_code=XfersBankCode.BPD_KALBAR_UUS,
        swift_bank_code='SYKBIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_KALSEL_UUS,
        bank_name="BPD KALIMANTAN SELATAN UUS (Unit Usaha Syariah)",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_KALSEL_UUS,
        instamoney_bank_code=InstamoneyBankCode.BPD_KALSEL_UUS,
        xfers_bank_code=XfersBankCode.BPD_KALSEL_UUS,
        swift_bank_code='SYKSIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_KALTIM_UUS,
        bank_name="BPD KALIMANTAN TIMUR UUS (Unit Usaha Syariah)",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_KALTIM_UUS,
        instamoney_bank_code=InstamoneyBankCode.BPD_KALTIM_UUS,
        xfers_bank_code=XfersBankCode.BPD_KALTIM_UUS,
        swift_bank_code='SYKTIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_SUMSEL_BABEL_UUS,
        bank_name="BPD SUMATERA SELATAN DAN BANGKA BELITUNG UUS (Unit Usaha Syariah)",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_SUMSEL_BABEL_UUS,
        instamoney_bank_code=InstamoneyBankCode.BPD_SUMSEL_BABEL_UUS,
        xfers_bank_code=XfersBankCode.BPD_SUMSEL_BABEL_UUS,
        swift_bank_code='SYSSIDJ1'
    ),
    Bank(
        bank_code=BankCodes.DKI_UUS,
        bank_name="BANK DKI UUS (Unit Usaha Syariah)",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.DKI_UUS,
        instamoney_bank_code=InstamoneyBankCode.DKI_UUS,
        xfers_bank_code=XfersBankCode.DKI_UUS,
        swift_bank_code='SYDKIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_ACEH_UUS,
        bank_name="BANK ACEH UUS (Unit Usaha Syariah)",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_ACEH_UUS,
        instamoney_bank_code=InstamoneyBankCode.BPD_ACEH_UUS,
        xfers_bank_code=XfersBankCode.BPD_ACEH_UUS,
        swift_bank_code='SYACIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_SUMUT_UUS,
        bank_name="BANK SUMATERA UTARA UUS (Unit Usaha Syariah)",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_SUMUT_UUS,
        instamoney_bank_code=InstamoneyBankCode.BPD_SUMUT_UUS,
        xfers_bank_code=XfersBankCode.BPD_SUMUT_UUS,
        swift_bank_code='SYSUIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_DIY_UUS,
        bank_name="BPD YOGYAKARTA UUS (Unit Usaha Syariah)",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_DIY_UUS,
        instamoney_bank_code=InstamoneyBankCode.BPD_DIY_UUS,
        xfers_bank_code=XfersBankCode.BPD_DIY_UUS,
        swift_bank_code='SYYKIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_JATENG_UUS,
        bank_name="BPD JAWA TENGAH UUS (Unit Usaha Syariah)",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_JATENG_UUS,
        instamoney_bank_code=InstamoneyBankCode.BPD_JATENG_UUS,
        xfers_bank_code=XfersBankCode.BPD_JATENG_UUS,
        swift_bank_code='SYJGIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_JATIM_UUS,
        bank_name="BPD JAWA TIMUR UUS (Unit Usaha Syariah)",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_JATIM_UUS,
        instamoney_bank_code=InstamoneyBankCode.BPD_JATIM_UUS,
        xfers_bank_code=XfersBankCode.BPD_JATIM_UUS,
        swift_bank_code='SYJTIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BPD_SULSELBAR_UUS,
        bank_name="BPD SULAWESI SELATAN DAN SULAWESI BARAT UUS (Unit Usaha Syariah)",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BPD_SULSELBAR_UUS,
        instamoney_bank_code=InstamoneyBankCode.BPD_SULSELBAR_UUS,
        xfers_bank_code=XfersBankCode.BPD_SULSELBAR_UUS,
        swift_bank_code='SYWSIDJ1'
    ),
    Bank(
        bank_code=BankCodes.HSBC_UUS,
        bank_name="THE HONGKONG & SHANGHAI BANKING CORP UUS (Unit Usaha Syariah)",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.HSBC_UUS,
        instamoney_bank_code=InstamoneyBankCode.HSBC_UUS,
        xfers_bank_code=XfersBankCode.HSBC_UUS,
        swift_bank_code='HSBCIDJA'
    ),
    Bank(
        bank_code=BankCodes.EKSPOR,
        bank_name="BANK EXIMBANK",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.EKSPOR,
        instamoney_bank_code=InstamoneyBankCode.EKSPOR,
        xfers_bank_code=XfersBankCode.EKSPOR,
        swift_bank_code='LPEIIDJ1'
    ),
    Bank(
        bank_code=BankCodes.BTPN_UUS,
        bank_name="BANK BTPN SYARIAH",
        min_account_number=7,
        xendit_bank_code=XenditBankCode.BTPN_UUS,
        instamoney_bank_code=InstamoneyBankCode.BTPN_UUS,
        xfers_bank_code=XfersBankCode.BTPN_UUS,
        swift_bank_code='BTPNIDJA'
    ),
    Bank(
        bank_code=BankCodes.BTN_UUS,
        bank_name="BANK TABUNGAN NEGARA (PERSERO) (BTN) UUS (Unit Usaha Syariah)",
        min_account_number=16,
        xendit_bank_code=XenditBankCode.BTN_UUS,
        instamoney_bank_code=InstamoneyBankCode.BTN_UUS,
        xfers_bank_code=XfersBankCode.BTN_UUS,
        swift_bank_code='SYBTIDJ1'
    ),
    Bank(
        bank_code=BankCodes.CIMB_NIAGA_UUS,
        bank_name="BANK CIMB NIAGA, Tbk UUS (Unit Usaha Syariah)",
        min_account_number=12,
        xendit_bank_code=XenditBankCode.CIMB_NIAGA_UUS,
        instamoney_bank_code=InstamoneyBankCode.CIMB_NIAGA_UUS,
        xfers_bank_code=XfersBankCode.CIMB_NIAGA_UUS,
        swift_bank_code='SYNAIDJ1'
    ),
    Bank(
        bank_code=BankCodes.OCBC_NISP_UUS,
        bank_name="BANK OCBC NISP, Tbk UUS (Unit Usaha Syariah)",
        min_account_number=12,
        xendit_bank_code=XenditBankCode.OCBC_NISP_UUS,
        instamoney_bank_code=InstamoneyBankCode.OCBC_NISP_UUS,
        xfers_bank_code=XfersBankCode.OCBC_NISP_UUS,
        swift_bank_code='SYONIDJ1'
    ),
    Bank(
        bank_code=BankCodes.DANAMON_UUS,
        bank_name="BANK DANAMON INDONESIA, Tbk UUS (Unit Usaha Syariah)",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.DANAMON_UUS,
        instamoney_bank_code=InstamoneyBankCode.DANAMON_UUS,
        xfers_bank_code=XfersBankCode.DANAMON_UUS,
        swift_bank_code='SYBDIDJ1'
    ),
    Bank(
        bank_code=BankCodes.PERMATA_UUS,
        bank_name="BANK PERMATA, Tbk UUS (Unit Usaha Syariah)",
        min_account_number=10,
        xendit_bank_code=XenditBankCode.PERMATA_UUS,
        instamoney_bank_code=InstamoneyBankCode.PERMATA_UUS,
        xfers_bank_code=XfersBankCode.PERMATA_UUS,
        swift_bank_code='SYBBIDJ1'
    ),
)


class BankManager(object):

    @classmethod
    def get_by_name_or_none(cls, bank_name):
        return BankModel.objects.filter(bank_name=bank_name).first()

    @classmethod
    def get_by_code_or_none(cls, bank_code):
        return BankModel.objects.filter(bank_code=bank_code).first()

    @classmethod
    def get_bank_names(cls):
        return list(BankModel.objects.filter(is_active=True).values_list('bank_name', flat=True))

    @classmethod
    def get_bank_names_v2(cls):
        return BankModel.objects.all().values('bank_name', 'min_account_number')

    @classmethod
    def get_by_method_bank_code(cls, bank_code):
        return BankModel.objects.filter(
            Q(xendit_bank_code=bank_code) |
            Q(xfers_bank_code=bank_code) |
            Q(instamoney_bank_code=bank_code)
        ).first()

    @classmethod
    def get_by_id_or_none(cls, bank_id):
        return BankModel.objects.filter(id=bank_id, is_active=True).first()

    @classmethod
    def get_by_all_bank_code_or_none(cls, bank_code):
        return BankModel.objects.filter(
            Q(bank_code=bank_code)
            | Q(xendit_bank_code=bank_code)
            | Q(xfers_bank_code=bank_code)
            | Q(instamoney_bank_code=bank_code)
        ).first()

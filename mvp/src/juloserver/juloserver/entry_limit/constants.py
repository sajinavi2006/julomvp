from builtins import object


class CreditLimitGenerationReason(object):
    ENTRY_LEVEL_LIMIT = 'Entry Level Credit Limit Generation'
    UPDATE_ADJUSTMENT_FACTOR = 'limit adjustment factor update'
    RECALCULATION_WITH_CLCS = 'Credit Limit Recalculation With CLCS Score'
    UPDATE_MONTHLY_INCOME = 'Update Monthly Income'


class JobsConst:
    IBU_RUMAH_TANGGA = 'Ibu rumah tangga'
    STAF_RUMAH_TANGGA = 'Staf rumah tangga'
    TIDAK_BEKERJA = 'Tidak bekerja'
    MAHASISWA = 'Mahasiswa'
    JOBLESS_CATEGORIES = {TIDAK_BEKERJA, STAF_RUMAH_TANGGA, IBU_RUMAH_TANGGA, MAHASISWA}

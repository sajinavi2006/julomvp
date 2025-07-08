from builtins import object
from dateutil.relativedelta import relativedelta


class LocConst(object):
    BRAND = 'JULOKredit'
    STATUS_NONE = 'none'
    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_FREEZE = 'freeze'
    DEFAULT_LIMIT = 300000
    SERVICE_FEE_RATE = 0.08
    LATE_FEE_RATE = 0.2
    LATE_FEE_MIN_AMOUNT = 15000
    INTEREST_RATE = 0.03
    PAYMENT_GRACE_PERIOD = 3
    MIN_STATEMENT_DAY = 1
    MAX_STATEMENT_DAY = 28
    DEFAULT_STATEMENT_DAY = MAX_STATEMENT_DAY
    DEFAULT_FREEZE_REASON = 'not minimum paid over 30 days'
    PIN_MODE_ENFORCING = 'enforcing'
    PIN_MODE_PERMISSIVE = 'permissive'
    RESET_PIN_MESSAGE = 'PIN {} anda telah berhasil di reset'.format(BRAND)


class LocTransConst(object):
    TYPE_PURCHASE = 'purchase'
    TYPE_PAYMENT = 'payment'
    TYPE_LATE_FEE = 'late_fee'
    TYPE_INTEREST = 'interest'
    STATUS_IN_PROCESS = 'in_process'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    CHANNEL_FASPAY = 'faspay'
    CHANNEL_SEPULSA = 'sepulsa'
    CHANNEL_JULO = 'julo'


class LocNotifConst(object):
    TYPE_STATEMENT_NOTICE = 'statement_notice'
    TYPE_PAYMENT_REMINDER = 'payment_reminder'
    CHANNEL_EMAIL = 'email'
    CHANNEL_SMS = 'sms'
    CHANNEL_PN = 'push_notification'

    NOTIFICATION_MATRIX = {
        TYPE_STATEMENT_NOTICE: {
            CHANNEL_PN: [relativedelta(days=0)],
            CHANNEL_SMS: [relativedelta(days=0)],
            CHANNEL_EMAIL: [relativedelta(days=0)],
        },
        TYPE_PAYMENT_REMINDER: {
            CHANNEL_EMAIL: [relativedelta(days=0), relativedelta(days=-1)],
            CHANNEL_SMS: [relativedelta(days=0), relativedelta(days=-2)],
            CHANNEL_PN: [relativedelta(days=0), relativedelta(days=-2)],
        }
    }


class LocResponseMessageTemplate(object):
    GENERAL_ERROR = 'Mohon maaf, terjadi kendala dalam proses pembelian produk. Silakan coba beberapa saat lagi.'
    INVALID_NUMBER = 'Nomor tidak terdaftar.'
    BALANCE_INSUFFICIENT = 'Balance Anda tidak cukup.'
    DOUBLE_TRANSACTION = 'Terdapat transaksi yang sedang dalam proses, Coba beberapa saat lagi.'
    ACCOUNT_ELECTRICITY_INVALID = 'Nomor Meter / ID Pelanggan tidak terdaftar.'
    LOC_NOT_FOUND = 'Mohon maaf Anda belum memiliki JuloKredit'

class LocCollConst(object):
    Tmin1 = 'due_soon'
    T0 = 'due_today'
    T1to30 = 'dpd_1_to_30'
    Tplus30 = 'overdue_more_than30'


class LocErrorTemplate(object):
    LOC_NOT_FOUND = {'code': 'LOC_01',
                     'message': 'Mohon maaf Anda belum memiliki JuloKredit'}
    LOC_PIN_INVALID = {
        'code': 'LOC-06',
        'message': 'PIN yang Anda masukkan salah!'
    }
    LOC_PIN_FORMAT_INVALID = {
        'code': 'LOC-07',
        'message': 'Format PIN tidak valid, PIN harus teridiri dari 6 digit angka'
    }
    LOC_PIN_UPDATE_NOT_OLD_PIN = {
        'code': 'LOC-08',
        'message': 'Mohon sertakan PIN lama Anda untuk mengganti PIN'
    }
    RESET_KEY_INVALID = {
        'code': 'LOC-09',
        'message': 'Mohon maaf reset PIN key JULOKredit Anda tidak valid'
    }
    RESET_KEY_EXPIRED = {
        'code': 'LOC-10',
        'message': 'Mohon maaf link reset PIN JULOKredit Anda sudah expired, silahkan kembali ke aplikasi JULO Anda untuk mendapatkan link reset PIN anda kembali'
    }
    PIN_MISMATCH = {
        'code': 'LOC-11',
        'message': 'PIN yang anda masukkan tidak cocok!'
    }
    GENERAL_ERROR = {
        'code': 'GE-01',
        'message': 'Mohon maaf ada Kesalahan di server! silahkan hubungi customer service'
    }
    LOC_PIN_NOT_SET = {
        'code': 'LOC-12',
        'message': 'Mohon maaf Anda belum menentukan PIN JULOKredit Anda, silahkan set pin terlebih dahulu agar dapat melakukan transaksi'
    }

ACTION_TYPE_CHOICES = (("email", "email"), ("deeplink", "deeplink"))


class SuggestedAnswerConst:
    CACHE_PREFIX = "feedback_suggested_answers"
    RATE_LIMIT = 10
    RATE_LIMIT_PERIOD = 3600  # 1 hour in seconds
    API_KEY = "WB3tFfc5Si0EEkhg9B4NHnRFKWFij6rY"

    class ErrorMessage:
        MSG_FIELD_MISSING_REQUIRED = "Field wajid diisi semua"
        MSG_SUGGESTED_ANSWER_NOT_FOUND = "Jawaban tidak ditemukan"
        MSG_SUBMISSION_DATA_INVALID = "Data pengajuan tidak valid"
        MSG_INTERNAL_ERROR_SERVER = "Terjadi kesalahan pada server"
        MSG_SUCCESSFULLY_SUBMIT = "Feedback berhasil disimpan"
        MSG_IP_ADDRESS_NOT_FOUND = "Identifier client tidak ditemukan"
        MSG_FEEDBACK_SUBMISSION_RATE_LIMI = "Pengiriman feedback sudah mencapai batas maksimal"

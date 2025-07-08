class StreamlinedTemplateCode:
    J1_DPD_MINUS_3 = 'nexmo_robocall_j1_-3'
    J1_DPD_MINUS_5 = 'nexmo_robocall_j1_-5'


class NexmoVoiceRateLimit:
    PAYMENT_REMINDER = 12
    PAYMENT_REMINDER_REDIS_KEY = 'nexmo:nexmo_voice_rate_limit_payment_reminder'


RANDOMIZER_PHONE_NUMBER_TEMPLATE_CODES = [
    StreamlinedTemplateCode.J1_DPD_MINUS_3, StreamlinedTemplateCode.J1_DPD_MINUS_5]

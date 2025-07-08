SURVEY_TYPE_CHOICES = (
    ("account-deletion-request", "Account Deletion Request"),
    ("complaint-form", "Complaint Form"),
    ("autodebet-deactivation", "Autodebet Deactivation"),
)

USER_STATUS_CHOICES = (
    ("account", "Account"),
    ("application", "Application"),
)

ANSWER_TYPE_CHOICES = (
    ("single-choice", "Single Choice"),
    ("number", "Number"),
    ("free-text", "Free Text"),
    ("multiple-choice", "Multiple Choice"),
    ("custom-page", "Custom Page"),
)

IN_ANSWER_TYPE_CHOICES = (("multi-option", "Multi Option"),)

QUESTION_CACHE_TIMEOUT = 1800  # 30 minutes
QUESTION_CACHE_KEY = "inapp_survey:question-{}"


class MessagesConst:
    NO_VALID_APPLICATION = "Application was not found"
    NO_QUESTION_RELATED_TO_STATUS = "No questions related to user's application or account status"
    SURVEY_TYPE_NOT_SUPPORTED = "Survey type is not supported"
    DUPLICATE_BOTTOM_POSITION = "Only one answer can have bottom_position set to True."
    DUPLICATE_MULTI_OPTION = "Only one answer can have answer type set to multi_option."

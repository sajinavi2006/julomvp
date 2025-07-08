from ...statuses import ApplicationStatusCodes

# statuses which has an action handler

STATUSES_WHICH_HAS_HANDLER = (
    # 100
    ApplicationStatusCodes.FORM_CREATED,
    # 105
    ApplicationStatusCodes.FORM_PARTIAL,

    # 106
    ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,

    # 111
    ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,

    # 120
    ApplicationStatusCodes.DOCUMENTS_SUBMITTED,

    # 122
    ApplicationStatusCodes.DOCUMENTS_VERIFIED,

    # 130
    ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,

    # 131
    ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,

    # 132
    ApplicationStatusCodes.APPLICATION_RESUBMITTED,

    # 133
    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,

    # 134
    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,

    # 135
    ApplicationStatusCodes.APPLICATION_DENIED,

    # 136
    ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,

    # 137
    ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,

    # 138
    ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,

    # 139
    ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,

    # 140
    ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,

    # 141
    ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,

    # 142
    ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,

    # 143
    ApplicationStatusCodes.OFFER_EXPIRED,

    # 150
    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,

    # 160
    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,

    # 161
    ApplicationStatusCodes.ACTIVATION_CALL_FAILED,

    # 162
    ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,

    # 163
    ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,

    # 164
    ApplicationStatusCodes.NAME_VALIDATE_ONGOING,

    # 170
    ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,

    # 171
    ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,

    # 172
    ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,

    # 174
    ApplicationStatusCodes.DOWN_PAYMENT_EXPIRED,

    # 180
    ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,

    # 181
    ApplicationStatusCodes.FUND_DISBURSAL_FAILED,

)

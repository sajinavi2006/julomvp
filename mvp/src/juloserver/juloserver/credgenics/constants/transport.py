class Path:
    # CONFIRM FOR BULK UPLOAD PATH; assume this is the path for bulk create/update/etc
    PATH_LOAN = "/api/v1/loan"


class Header:
    AUTH_TOKEN = "authenticationtoken"
    CONTENT_TYPE = "Content-Type"

    class Value:
        JSON = "application/json"

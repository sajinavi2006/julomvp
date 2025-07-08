class JWTErrorConstant(object):
    INVALID_TOKEN = "Invalid token."
    EXPIRED_TOKEN = "The token is expired."
    MISSING_USER_IDENTIFIER = "Missing user identifier id in token"
    APPLICATION_ID_REQUIRED = "Application ID is required for products other than Grab."


class JWTConstant(object):
    EXPIRED_IN_DAYS = 30

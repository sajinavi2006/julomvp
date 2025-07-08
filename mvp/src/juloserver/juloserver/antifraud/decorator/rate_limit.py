import logging
from functools import wraps

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.ratelimit.decorator import rate_limit_incoming_http
from juloserver.ratelimit.constants import (
    RateLimitTimeUnit,
    RateLimitParameter,
    RateLimitAlgorithm,
)

logger = logging.getLogger(__name__)


def antifraud_rate_limit(feature_name: str):
    """
    Decorator to apply rate limiting for antifraud-related features.

    Args:
        feature_name (str): The name of the feature whose rate limit configuration will be used.

    Returns:
        function: The decorated function wrapped with the appropriate rate limit settings.

    Example usage:
        @antifraud_rate_limit(feature_name='fraud_detection')
        def some_view(request):
            pass
    """
    def decorator(func):
        @wraps(func)
        def wrapper(view, request, *args, **kwargs):

            feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.ANTIFRAUD_RATE_LIMIT,
                is_active=True
            ).last()

            if feature_setting:
                feature_rate_limit = feature_setting.parameters.get(feature_name)
                if feature_rate_limit and feature_rate_limit.get('is_active'):
                    max_count = feature_rate_limit.get('max_count')
                    time_unit = feature_rate_limit.get('time_unit')

                    rate_limit_decorator = rate_limit_incoming_http(
                        max_count=max_count,
                        time_unit=RateLimitTimeUnit[time_unit],
                        algo=RateLimitAlgorithm.SlidingWindow,
                        parameters=[
                            RateLimitParameter.Path,
                            RateLimitParameter.AuthenticatedUser,
                            RateLimitParameter.HTTPMethod
                        ]
                    )

                    decorated_func = rate_limit_decorator(func)

                    return decorated_func(view, request, *args, **kwargs)

            logger.info(
                {
                    'action': 'antifraud_rate_limit',
                    'feature_name': feature_name,
                    'message': 'feature setting is inactive'
                }
            )
            return func(view, request, *args, **kwargs)

        return wrapper
    return decorator

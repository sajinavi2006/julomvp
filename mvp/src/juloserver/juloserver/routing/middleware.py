"""
middleware.py
purpose: custom logic default of django_duplicated package
"""
import logging
import inspect
import fnmatch

from django.core import urlresolvers as urls
from django.conf import settings

from django_replicated.middleware import ReplicationMiddleware
from django_replicated.utils import routers, get_object_name

LOGGER = logging.getLogger(__name__)

class CustomReplicationMiddleware(ReplicationMiddleware):
    """custom class"""

    def process_request(self, request):
        if self.forced_state is not None:
            state = self.forced_state
            LOGGER.debug('state by .forced_state attr: %s', state)
        elif request.META.get(settings.REPLICATED_FORCE_STATE_HEADER) in ('master', 'slave'):
            state = request.META[settings.REPLICATED_FORCE_STATE_HEADER]
            LOGGER.debug('state by header: %s', state)
        else:
            state = 'master'
            LOGGER.debug('state by request method: %s', state)
            state = self.check_state_override(request, state)
            state = state if request.method in ['GET', 'HEAD'] else 'master'
            LOGGER.debug('state after override: %s', state)

            LOGGER.debug('init state: %s', state)
        routers.init(state)

    def get_state_override(self, request):
        overrides = settings.REPLICATED_VIEWS_OVERRIDES
        if not overrides:
            return

        match = urls.resolve(request.path_info)

        import_path = '%s.%s' % (get_object_name(inspect.getmodule(match.func)),
                                 get_object_name(match.func))

        for lookup_view in overrides:
            if (
                    self.is_override_matched(match, lookup_view) or
                    import_path == lookup_view or
                    fnmatch.fnmatchcase(request.path_info, lookup_view)
            ):
                return 'slave'

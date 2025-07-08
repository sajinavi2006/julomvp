from importlib import import_module

from django.conf import settings
from django.conf.urls import include, url
from django.utils.module_loading import module_has_submodule

INSTALLED_APPS = getattr(settings, 'INSTALLED_APPS', ())


def apps_urlpatterns(apps, recursive=False):
    """
    Helper function to return a URL pattern for apps.
    """
    urlpatterns = []
    if isinstance(apps, (list, tuple)):
        apps = (
            apps if recursive else set([app.split('.')[0] for app in apps if app in INSTALLED_APPS])
        )
        for app in apps:
            # print "app:", app
            mod = import_module(app)
            try:
                import_module('%s.urls' % app)
                urlpatterns += [
                    url(r'^%s/' % app.replace('.', '/'), include('%s.urls' % app, namespace=app))
                ]
            except ImportError:
                if module_has_submodule(mod, 'urls'):
                    raise

    return urlpatterns

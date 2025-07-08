def partner_protected_logic(function):
    def wrap(view, request, *args, **kwargs):
        return function(view, request, *args, **kwargs)

    wrap.__doc__ = function.__doc__
    wrap.__name__ = function.__name__

    return wrap

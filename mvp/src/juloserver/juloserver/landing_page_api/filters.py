from rest_framework import filters


class InFilterBackend(filters.BaseFilterBackend):
    """
        Adding additional filter for in. Using coma separate.
        for ex:
        - name__in=name-1,name-2
    """

    def filter_queryset(self, request, queryset, view):
        filter_fields = getattr(view, 'filter_fields', None)
        if not filter_fields:
            return queryset
        for field in filter_fields:
            filter_field = f'{field}__in'
            if filter_field in request.GET:
                filter_value = request.GET[filter_field].split(',')
                filter_kwargs = {filter_field: filter_value}
                queryset = queryset.filter(**filter_kwargs)
        return queryset

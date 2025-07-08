from rest_framework.permissions import IsAuthenticated


def crm_permission(role_list):
    class InnerClass(IsAuthenticated):
        def has_permission(self, request, view):
            if not super(InnerClass, self).has_permission(request, view):
                return False

            return request.user.groups.filter(name__in=role_list).exists()

    return InnerClass


def crm_permission_exclude(exclude_role_list):
    class InnerClass(IsAuthenticated):
        def has_permission(self, request, view):
            if not super(InnerClass, self).has_permission(request, view):
                return False

            return (
                request.user.groups
                    .filter(id__isnull=False)
                    .exclude(name__in=exclude_role_list)
                    .exists()
            )

    return InnerClass

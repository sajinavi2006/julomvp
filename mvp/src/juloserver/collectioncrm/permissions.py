from rest_framework import permissions


class AgentSupervisor(permissions.BasePermission):
    """
    Object-level permission to only allow owners of an object to edit it.
    """
    def has_object_permission(self, request, obj ):
        return request.user.has_perm('julo.add_agent')
    def has_permission(self, request, view):
        return request.user.has_perm('julo.add_agent')


class AgentPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.groups.filter(name__in=['agent1', 'agent2', 'agent3']).exists()

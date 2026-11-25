from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

def is_admin(user):
    return user.is_authenticated and user.is_active and user.is_superuser

def admin_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not is_admin(request.user):
            raise PermissionDenied('Administrator access is required.')
        return view(request, *args, **kwargs)
    return wrapped

def is_manager(user):
    return user.is_authenticated and (user.is_superuser or user.groups.filter(name='Managers').exists())

def manager_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not is_manager(request.user):
            raise PermissionDenied('Manager access is required.')
        return view(request, *args, **kwargs)
    return wrapped

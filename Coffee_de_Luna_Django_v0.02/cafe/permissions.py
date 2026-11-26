from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

def is_admin(user):
    return bool(user) and user.is_authenticated and user.is_active and user.is_superuser

def admin_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not is_admin(request.user):
            raise PermissionDenied('Administrator access is required.')
        return view(request, *args, **kwargs)
    return wrapped

def is_manager(user):
    return bool(user) and user.is_authenticated and user.is_active and (user.is_superuser or user.groups.filter(name='Managers').exists())

def is_team(user):
    return bool(user) and user.is_authenticated and user.is_active and (user.is_superuser or user.is_staff or
        user.groups.filter(name__in=['Managers', 'Cashiers']).exists())

def is_customer(user):
    return bool(user) and user.is_authenticated and user.is_active and not is_team(user) and user.groups.filter(name='Customers').exists()

def staff_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not is_team(request.user):
            raise PermissionDenied('Staff access is required.')
        return view(request, *args, **kwargs)
    return wrapped

def customer_required(view):
    @login_required(login_url='customer_login')
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not is_customer(request.user):
            raise PermissionDenied('A customer account is required.')
        return view(request, *args, **kwargs)
    return wrapped

def manager_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not is_manager(request.user):
            raise PermissionDenied('Manager access is required.')
        return view(request, *args, **kwargs)
    return wrapped

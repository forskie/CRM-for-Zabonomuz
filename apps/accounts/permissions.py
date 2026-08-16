from functools import wraps
from typing import Callable

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import UserRole


def owner_required(view_func: Callable):
    """Allow only an authenticated OWNER to manage accounts."""

    @login_required
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if not request.user.is_owner:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped_view


def operational_required(view_func: Callable):
    """Allow OWNER and ADMIN operational access; TEACHER receives a server-side 403."""

    @login_required
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if request.user.role not in (UserRole.OWNER, UserRole.ADMIN):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped_view

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def dashboard(request):
    """Temporary protected landing page; dashboard metrics arrive in stage 9."""
    return render(request, "core/dashboard.html")

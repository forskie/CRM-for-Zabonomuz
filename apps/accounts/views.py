from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import CreateView

from .forms import ManagedUserCreateForm, ManagedUserUpdateForm
from .models import User, UserRole
from .permissions import owner_required


class CRMLoginView(LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True


@owner_required
def user_list(request):
    return render(request, "accounts/user_list.html", {"users": User.objects.all()})


@method_decorator(owner_required, name="dispatch")
class UserCreateView(CreateView):
    model = User
    form_class = ManagedUserCreateForm
    template_name = "accounts/user_form.html"
    success_url = reverse_lazy("accounts:user-list")


@owner_required
def user_edit(request, pk: int):
    user = get_object_or_404(User, pk=pk)
    if user.role == UserRole.OWNER:
        raise PermissionDenied("Учётная запись владельца не изменяется через этот экран.")

    form = ManagedUserUpdateForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("accounts:user-list")
    return render(request, "accounts/user_form.html", {"form": form, "editing": True, "managed_user": user})

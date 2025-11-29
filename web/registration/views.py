"""Views for team registration."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from core.auth_utils import require_permission

from .forms import RegistrationForm
from .models import TeamRegistration


def register(request: HttpRequest) -> HttpResponse:
    """Public registration form (no authentication required)."""
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Registration submitted successfully! You will receive an email once reviewed.")
            return redirect("registration_register")
    else:
        form = RegistrationForm()

    return render(request, "registration/register.html", {"form": form})


@login_required
@require_permission("gold_team")
def review_list(request: HttpRequest) -> HttpResponse:
    """Admin review list of all registrations (Gold Team and Admin only)."""
    status_filter = request.GET.get("status", "")

    registrations = TeamRegistration.objects.all()
    if status_filter:
        registrations = registrations.filter(status=status_filter)

    return render(
        request,
        "registration/review_list.html",
        {
            "registrations": registrations,
            "status_filter": status_filter,
            "status_choices": TeamRegistration.STATUS_CHOICES,
        },
    )


@login_required
@require_permission("gold_team")
def approve_registration(request: HttpRequest, registration_id: int) -> HttpResponse:
    """Approve a registration (Gold Team and Admin only)."""
    if request.method != "POST":
        return redirect("registration_review_list")

    registration = get_object_or_404(TeamRegistration, id=registration_id)
    if request.user.is_authenticated:
        registration.approve(request.user)
    messages.success(request, f"Registration for {registration.school_name} has been approved.")

    return redirect("registration_review_list")


@login_required
@require_permission("gold_team")
def reject_registration(request: HttpRequest, registration_id: int) -> HttpResponse:
    """Reject a registration (Gold Team and Admin only)."""
    registration = get_object_or_404(TeamRegistration, id=registration_id)

    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        if not reason:
            messages.error(request, "Please provide a reason for rejection.")
            return render(
                request,
                "registration/reject_confirm.html",
                {"registration": registration},
            )

        registration.reject(reason)
        messages.success(request, f"Registration for {registration.school_name} has been rejected.")
        return redirect("registration_review_list")

    return render(request, "registration/reject_confirm.html", {"registration": registration})

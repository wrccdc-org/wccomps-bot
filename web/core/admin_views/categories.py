"""Admin views for ticket category management."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from ..auth_utils import require_permission


@require_permission("gold_team", "ticketing_admin")
def admin_categories(request: HttpRequest) -> HttpResponse:
    """List all ticket categories."""
    from ticketing.models import TicketCategory

    categories = TicketCategory.objects.all()
    return render(request, "admin/categories.html", {"categories": categories})


@require_permission("gold_team", "ticketing_admin")
def admin_category_create(request: HttpRequest) -> HttpResponse:
    """Create a new ticket category."""
    from ticketing.models import TicketCategory

    if request.method == "POST":
        display_name = request.POST.get("display_name", "").strip()
        if not display_name:
            return render(
                request,
                "admin/category_form.html",
                {
                    "error": "Display name is required.",
                    "form_data": request.POST,
                },
            )

        TicketCategory.objects.create(
            display_name=display_name,
            points=int(request.POST.get("points", 0)),
            required_fields=request.POST.getlist("required_fields"),
            optional_fields=request.POST.getlist("optional_fields"),
            variable_points="variable_points" in request.POST,
            variable_cost_note=request.POST.get("variable_cost_note", ""),
            min_points=int(request.POST.get("min_points", 0)),
            max_points=int(request.POST.get("max_points", 0)),
            user_creatable="user_creatable" in request.POST,
            sort_order=int(request.POST.get("sort_order", 0)),
        )
        return redirect("admin_categories")

    return render(request, "admin/category_form.html", {})


@require_permission("gold_team", "ticketing_admin")
def admin_category_edit(request: HttpRequest, category_id: int) -> HttpResponse:
    """Edit an existing ticket category."""
    from ticketing.models import TicketCategory

    try:
        category = TicketCategory.objects.get(pk=category_id)
    except TicketCategory.DoesNotExist:
        return HttpResponse("Category not found", status=404)

    if request.method == "POST":
        display_name = request.POST.get("display_name", "").strip()
        if not display_name:
            return render(
                request,
                "admin/category_form.html",
                {
                    "category": category,
                    "error": "Display name is required.",
                    "form_data": request.POST,
                },
            )

        category.display_name = display_name
        category.points = int(request.POST.get("points", 0))
        category.required_fields = request.POST.getlist("required_fields")
        category.optional_fields = request.POST.getlist("optional_fields")
        category.variable_points = "variable_points" in request.POST
        category.variable_cost_note = request.POST.get("variable_cost_note", "")
        category.min_points = int(request.POST.get("min_points", 0))
        category.max_points = int(request.POST.get("max_points", 0))
        category.user_creatable = "user_creatable" in request.POST
        category.sort_order = int(request.POST.get("sort_order", 0))
        category.save()
        return redirect("admin_categories")

    return render(request, "admin/category_form.html", {"category": category})


@require_permission("gold_team", "ticketing_admin")
def admin_category_delete(request: HttpRequest, category_id: int) -> HttpResponse:
    """Delete a ticket category."""
    from ticketing.models import TicketCategory

    try:
        category = TicketCategory.objects.get(pk=category_id)
    except TicketCategory.DoesNotExist:
        return HttpResponse("Category not found", status=404)

    ticket_count = category.tickets.count()

    if request.method == "POST":
        category.delete()
        return redirect("admin_categories")

    return render(
        request,
        "admin/category_delete.html",
        {
            "category": category,
            "ticket_count": ticket_count,
        },
    )

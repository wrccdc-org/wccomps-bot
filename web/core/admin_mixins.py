"""Reusable admin mixins for WCComps."""

import csv
from typing import Any

from django.contrib import admin
from django.http import HttpRequest, HttpResponse


class CSVExportMixin:
    """Mixin to add CSV export action to ModelAdmin.

    Usage:
        class MyModelAdmin(CSVExportMixin, admin.ModelAdmin):
            csv_fields = ["id", "name", "team__team_name", "created_at"]
            csv_filename = "my_export.csv"
            actions = ["export_as_csv"]

    Supports dotted notation for FK traversal (e.g., "team__team_name").
    """

    csv_fields: list[str] = []
    csv_filename: str = "export.csv"
    csv_headers: list[str] | None = None

    def _get_field_value(self, obj: Any, field: str) -> Any:
        """Get field value, supporting dotted notation for FK traversal."""
        value = obj
        for part in field.split("__"):
            if value is None:
                return ""
            value = getattr(value, part, "")
        return value if value is not None else ""

    @admin.action(description="Export selected as CSV")
    def export_as_csv(self, request: HttpRequest, queryset: Any) -> HttpResponse:
        """Export selected items as CSV."""
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{self.csv_filename}"'

        writer = csv.writer(response)

        headers = self.csv_headers if self.csv_headers else self.csv_fields
        writer.writerow(headers)

        for obj in queryset:
            writer.writerow([self._get_field_value(obj, field) for field in self.csv_fields])

        return response


class ReadOnlyModelAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """ModelAdmin that prevents add, change, and delete operations.

    Usage:
        @admin.register(MyModel)
        class MyModelAdmin(ReadOnlyModelAdmin):
            list_display = ["field1", "field2"]
    """

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

"""Ticket categories and configuration."""

from typing import TypedDict


class TicketCategoryConfig(TypedDict, total=False):
    display_name: str
    points: int
    required_fields: list[str]
    optional_fields: list[str]
    warning: str
    variable_cost_note: str


TICKET_CATEGORIES: dict[str, TicketCategoryConfig] = {
    "service-scoring-validation": {
        "display_name": "Service Scoring Validation",
        "points": 0,
        "required_fields": ["service_name"],
        "optional_fields": ["description"],
        "warning": "Free initially, tracked for abuse (5pt penalty if misused)",
    },
    "box-reset": {
        "display_name": "Box Reset / Scrub",
        "points": 60,
        "required_fields": ["hostname", "ip_address"],
        "optional_fields": [],
    },
    "scoring-service-check": {
        "display_name": "Scoring Service Check",
        "points": 10,
        "required_fields": ["service_name"],
    },
    "blackteam-phone-consultation": {
        "display_name": "Black Team Phone Consultation",
        "points": 100,
        "required_fields": ["description"],
    },
    "blackteam-handson-consultation": {
        "display_name": "Black Team Hands-on Consultation",
        "points": 200,
        "required_fields": ["hostname", "description"],
        "variable_cost_note": "If consultation exceeded 45 minutes, ticket lead will manually adjust to 300 points",
    },
    "other": {
        "display_name": "Other / General Issue",
        "points": 0,
        "required_fields": ["description"],
        "warning": "Free initially - ticket lead will manually adjust points if needed",
    },
}

"""Helper functions for safe model creation with validation."""

import logging
from typing import Any, TypeVar

from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError
from django.db.models import Model

T = TypeVar("T", bound=Model)

logger = logging.getLogger(__name__)


async def validated_create(model_class: type[T], **kwargs: Any) -> T:
    """
    Create a model instance with full validation before saving.

    This catches field constraint violations (like null=False) before
    they reach the database, providing better error messages.

    Args:
        model_class: Django model class to create
        **kwargs: Field values for the model

    Returns:
        Created model instance

    Raises:
        ValidationError: If validation fails

    Example:
        ticket = await validated_create(
            Ticket,
            ticket_number="T001-001",
            team=team,
            hostname="",  # Must be "" not None for non-nullable CharField
        )
    """

    @sync_to_async
    def _create_with_validation() -> T:
        # Create instance without saving
        instance = model_class(**kwargs)

        # Validate all fields
        try:
            instance.full_clean()
        except ValidationError as e:
            # Log detailed error for debugging
            logger.exception(f"Validation failed for {model_class.__name__}: {e.message_dict}")
            raise

        # Save to database
        instance.save()
        return instance

    return await _create_with_validation()

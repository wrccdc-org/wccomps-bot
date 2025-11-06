"""Tests for model validation helpers."""

import pytest
from django.core.exceptions import ValidationError
from team.models import Team
from bot.model_helpers import validated_create


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestValidatedCreate:
    """Test validated_create helper function."""

    async def test_validated_create_success(self) -> None:
        """Test successful creation with valid data."""
        team = await validated_create(
            Team,
            team_number=16,
            team_name="Test Team",
            authentik_group="WCComps_BlueTeam16",
            max_members=5,
        )

        assert team.id is not None
        assert team.team_number == 16
        assert team.team_name == "Test Team"
        assert team.authentik_group == "WCComps_BlueTeam16"
        assert team.max_members == 5

    async def test_validated_create_validation_error_null_field(self) -> None:
        """Test validation error for null value in non-nullable field."""
        with pytest.raises(ValidationError) as exc_info:
            await validated_create(
                Team,
                team_number=17,
                team_name=None,  # Required field
                authentik_group="WCComps_BlueTeam17",
            )

        # Validation caught the null team_name
        assert "team_name" in exc_info.value.message_dict

    async def test_validated_create_validation_error_unique_constraint(self) -> None:
        """Test validation error for unique constraint violation."""
        # Create first team
        await validated_create(
            Team,
            team_number=18,
            team_name="Team 18",
            authentik_group="WCComps_BlueTeam18",
        )

        # Try to create duplicate team_number
        with pytest.raises(ValidationError) as exc_info:
            await validated_create(
                Team,
                team_number=18,  # Duplicate
                team_name="Team 18 Duplicate",
                authentik_group="WCComps_BlueTeam18_Dup",
            )

        # Validation caught the unique constraint
        assert "team_number" in exc_info.value.message_dict

    async def test_validated_create_uses_full_clean(self) -> None:
        """Test that full_clean is called before saving."""
        # This is tested implicitly by the validation error tests above
        # If full_clean() wasn't called, database constraints would raise
        # IntegrityError instead of ValidationError

        # Test with missing required field
        with pytest.raises(ValidationError):
            await validated_create(
                Team,
                team_number=19,
                # Missing team_name
                authentik_group="WCComps_BlueTeam19",
            )

    async def test_validated_create_minimal_fields(self) -> None:
        """Test creation with only required fields."""
        team = await validated_create(
            Team,
            team_number=20,
            team_name="Team 20",
            authentik_group="WCComps_BlueTeam20",
        )

        assert team.id is not None
        assert team.team_number == 20
        # max_members should have default value
        assert team.max_members == 10  # Default from model

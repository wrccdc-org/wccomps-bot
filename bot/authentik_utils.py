"""Utility functions for Authentik user management."""

import logging
import secrets
from typing import Any
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def validate_team_account(
    user_data: dict[str, Any], expected_username: str
) -> tuple[bool, str]:
    """Validate that a user account is a legitimate team account.

    Args:
        user_data: User data from Authentik API
        expected_username: Expected username (e.g., "team01")

    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    retrieved_username = user_data.get("username", "")

    # Check username starts with "team"
    if not retrieved_username.startswith("team"):
        return (
            False,
            f"Security error: User {retrieved_username} is not a team account",
        )

    # Check it matches expected username
    if retrieved_username != expected_username:
        return (
            False,
            f"Security error: Username mismatch (expected {expected_username}, got {retrieved_username})",
        )

    return (True, "")


def toggle_authentik_user(username: str, is_active: bool) -> tuple[bool, str]:
    """
    Enable or disable a team account in Authentik with safety checks.

    Args:
        username: Authentik username (e.g., "team01")
        is_active: True to enable, False to disable

    Returns:
        (success: bool, error_message: str)
    """
    headers = {
        "Authorization": f"Bearer {settings.AUTHENTIK_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(
            f"{settings.AUTHENTIK_URL}/api/v3/core/users/?username={username}",
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        users = response.json().get("results", [])

        if not users:
            return (False, "User not found")

        user = users[0]

        # Safety check: Verify this is actually a team account
        is_valid, error = validate_team_account(user, username)
        if not is_valid:
            return (False, error)

        response = requests.patch(
            f"{settings.AUTHENTIK_URL}/api/v3/core/users/{user['pk']}/",
            headers=headers,
            json={"is_active": is_active},
            timeout=10,
        )
        response.raise_for_status()
        return (True, "")
    except Exception as e:
        logger.error(f"Failed to toggle {username}: {e}")
        return (False, str(e))


async def toggle_all_blueteam_accounts(is_active: bool) -> tuple[int, int]:
    """
    Enable or disable all team01-team50 accounts in Authentik.

    Args:
        is_active: True to enable, False to disable

    Returns:
        (success_count, failed_count)
    """
    from asgiref.sync import sync_to_async

    success_count = 0
    failed_count = 0
    for i in range(1, 51):
        username = f"team{i:02d}"
        success, _ = await sync_to_async(toggle_authentik_user)(username, is_active)
        if success:
            success_count += 1
        else:
            failed_count += 1

    return (success_count, failed_count)


def generate_blueteam_password() -> str:
    """Generate a readable password for blue team accounts using EFF wordlist.

    Returns:
        str: Password in format like "Correct-Horse-742!" or "Battery-@199-Staple"
    """
    from xkcdpass import xkcd_password as xp

    # Get EFF long wordlist (7,776 words)
    wordlist = xp.generate_wordlist(wordfile=xp.locate_wordfile())

    # Generate 2 random words
    words = xp.generate_xkcdpassword(
        wordlist, numwords=2, delimiter="-", case="capitalize"
    )

    # Generate random number (100-999)
    number = secrets.randbelow(900) + 100

    # Select random special character
    special_chars = "!@#$%&*+"
    special_char = secrets.choice(special_chars)

    # Combine number and symbol (randomly choose order)
    if secrets.choice([True, False]):
        insert_value = f"{number}{special_char}"
    else:
        insert_value = f"{special_char}{number}"

    # Randomly choose position (0=before, 1=middle, 2=after)
    position = secrets.randbelow(3)

    # Insert number+symbol at chosen position
    word_parts = words.split("-")
    if position == 0:
        result = f"{insert_value}-{words}"
    elif position == 1:
        result = f"{word_parts[0]}-{insert_value}-{word_parts[1]}"
    else:  # position == 2
        result = f"{words}-{insert_value}"

    return result


def reset_blueteam_password(team_number: int, password: str) -> tuple[bool, str]:
    """Reset a blue team account's password in Authentik and enable the account.

    Args:
        team_number: Team number (1-50)
        password: New password to set

    Returns:
        Tuple of (success: bool, error_message: str or None)
    """
    if team_number < 1 or team_number > 50:
        return (False, "Team number must be between 1 and 50")

    username = f"team{team_number:02d}"

    headers = {
        "Authorization": f"Bearer {settings.AUTHENTIK_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        # Get user by username
        response = requests.get(
            f"{settings.AUTHENTIK_URL}/api/v3/core/users/?username={username}",
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        users = response.json().get("results", [])

        if not users:
            return (False, f"User {username} not found")

        user = users[0]
        user_pk = user["pk"]

        # Safety check: Verify this is actually a team account
        is_valid, error = validate_team_account(user, username)
        if not is_valid:
            return (False, error)

        # Set password
        response = requests.post(
            f"{settings.AUTHENTIK_URL}/api/v3/core/users/{user_pk}/set_password/",
            headers=headers,
            json={"password": password},
            timeout=10,
        )
        response.raise_for_status()

        # Enable user account (set is_active=True)
        response = requests.patch(
            f"{settings.AUTHENTIK_URL}/api/v3/core/users/{user_pk}/",
            headers=headers,
            json={"is_active": True},
            timeout=10,
        )
        response.raise_for_status()

        return (True, "")

    except Exception as e:
        logger.error(f"Failed to reset password for {username}: {e}")
        return (False, str(e))


def parse_team_range(range_str: str) -> list[int]:
    """
    Parse team range string like "1,3,5-10,15" into list of team numbers.

    Args:
        range_str: String with comma-separated numbers and ranges (e.g., "1,3,5-10,15")

    Returns:
        List of unique team numbers, sorted

    Examples:
        "1,3,5" -> [1, 3, 5]
        "1-5" -> [1, 2, 3, 4, 5]
        "1,3,5-10,15" -> [1, 3, 5, 6, 7, 8, 9, 10, 15]
    """
    team_numbers: set[int] = set()

    for part in range_str.split(","):
        part = part.strip()
        if not part:
            continue

        if "-" in part:
            # Range like "5-10"
            try:
                start_str, end_str = part.split("-", 1)
                start_num = int(start_str.strip())
                end_num = int(end_str.strip())

                if start_num > end_num:
                    raise ValueError(f"Invalid range: {part} (start > end)")
                if start_num < 1 or end_num > 50:
                    raise ValueError(f"Team numbers must be 1-50, got: {part}")

                team_numbers.update(range(start_num, end_num + 1))
            except ValueError as e:
                raise ValueError(f"Invalid range format: {part}") from e
        else:
            # Single number
            try:
                num = int(part)
                if num < 1 or num > 50:
                    raise ValueError(f"Team number must be 1-50, got: {num}")
                team_numbers.add(num)
            except ValueError:
                raise ValueError(f"Invalid team number: {part}")

    return sorted(list(team_numbers))

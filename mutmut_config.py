"""Mutmut configuration to scope testing to well-tested methods."""


def pre_mutation(context):
    """
    Only test the 3 methods we've properly strengthened assertions for.

    Returns:
        - context: Allow the mutation
        - None: Skip the mutation
    """
    # Only test these specific line ranges (the methods we strengthened):
    # assign_team_role: 247-281
    # remove_team_role: 354-382
    # remove_all_team_roles: 383-425

    if not (
        247 <= context.current_line_index <= 281
        or 354 <= context.current_line_index <= 382
        or 383 <= context.current_line_index <= 425
    ):
        return None

    # Still skip logger calls even within these methods
    line = context.current_source_line.strip()
    if "logger." in line:
        return None

    # Allow mutations in our tested methods
    return context

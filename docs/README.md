# WCComps Documentation

## Specification Documents

- [User Roles and Stories](user-roles-and-stories.md) - Defines user roles, permissions, and user stories
- [UI Design System](ui-design-system.md) - Consistent patterns for navigation, layouts, components
- [API Documentation](api.md) - REST API endpoints and contracts
- [Architecture](ARCHITECTURE.md) - System architecture, workflows, and implementation details

## Quick Reference

### User Roles
| Role | Authentik Group | Primary Purpose |
|------|-----------------|-----------------|
| Blue Team | `WCComps_BlueTeam{N}` | Competition participants defending infrastructure |
| Red Team | `WCComps_RedTeam` | Attackers documenting successful attacks |
| Gold Team | `WCComps_GoldTeam` | Competition organizers and judges |
| White Team | `WCComps_WhiteTeam` | Inject graders |
| Orange Team | `WCComps_OrangeTeam` | Bonus/penalty adjustments |
| Ticketing Support | `WCComps_Ticketing_Support` | Handle participant support tickets |
| Ticketing Admin | `WCComps_Ticketing_Admin` | Elevated ticket management |
| Admin | `WCComps_Discord_Admin` | System administration |

### Key URLs
| Path | Purpose |
|------|---------|
| `/scoring/` | Leaderboard (Gold/White/Ticketing Admin/Admin) |
| `/scoring/incident/submit/` | Blue team incident submission |
| `/scoring/red-team/submit/` | Red team finding submission |
| `/scoring/orange-team/` | Orange team portal |
| `/tickets/` | Team ticket list (Blue Team) |
| `/ops/tickets/` | Ticket management (Support/Admin) |
| `/ops/group-role-mappings/` | Team member mappings (Gold/Admin) |
| `/ops/school-info/` | School contact information (Gold/Admin) |
| `/admin/` | Django admin (Staff) |

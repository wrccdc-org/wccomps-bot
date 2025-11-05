-- WCComps Database Schema

-- Competitions table
CREATE TABLE IF NOT EXISTS competitions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'inactive', -- 'inactive', 'active', 'ended'
    start_date TIMESTAMP,
    end_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Teams table
CREATE TABLE IF NOT EXISTS teams (
    id SERIAL PRIMARY KEY,
    team_number INTEGER NOT NULL UNIQUE, -- 1-50
    team_name VARCHAR(100) NOT NULL, -- e.g., 'BlueTeam01'
    authentik_group_name VARCHAR(255) NOT NULL, -- e.g., 'WCComps_BlueTeam01'
    enrollment_url TEXT,
    payment_status BOOLEAN DEFAULT FALSE,
    payment_date TIMESTAMP,
    competition_id INTEGER REFERENCES competitions(id),
    discord_role_id BIGINT,
    discord_category_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Discord links table
CREATE TABLE IF NOT EXISTS discord_links (
    id SERIAL PRIMARY KEY,
    discord_id BIGINT NOT NULL UNIQUE,
    discord_username VARCHAR(255),
    authentik_username VARCHAR(255) NOT NULL,
    authentik_user_id VARCHAR(255),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    unlinked_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- Audit logs table
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    action VARCHAR(100) NOT NULL, -- 'team_paid', 'user_linked', 'competition_started', etc.
    admin_user VARCHAR(255),
    target_entity VARCHAR(100), -- 'team', 'user', 'competition'
    target_id BIGINT,
    details JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Link tokens table (for /link command)
CREATE TABLE IF NOT EXISTS link_tokens (
    id SERIAL PRIMARY KEY,
    token VARCHAR(255) NOT NULL UNIQUE,
    discord_id BIGINT NOT NULL,
    discord_username VARCHAR(255),
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Link attempts table (for debugging and tracking all linking attempts)
CREATE TABLE IF NOT EXISTS link_attempts (
    id SERIAL PRIMARY KEY,
    discord_id BIGINT NOT NULL,
    discord_username VARCHAR(255),
    authentik_username VARCHAR(255),
    team_id INTEGER REFERENCES teams(id),
    success BOOLEAN NOT NULL,
    failure_reason VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX idx_teams_competition ON teams(competition_id);
CREATE INDEX idx_discord_links_team ON discord_links(team_id);
CREATE INDEX idx_discord_links_discord_id ON discord_links(discord_id);
CREATE INDEX idx_link_tokens_token ON link_tokens(token);
CREATE INDEX idx_link_attempts_discord_id ON link_attempts(discord_id);
CREATE INDEX idx_link_attempts_created_at ON link_attempts(created_at);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at);

-- Insert initial 50 teams
DO $$
BEGIN
    FOR i IN 1..50 LOOP
        INSERT INTO teams (team_number, team_name, authentik_group_name)
        VALUES (
            i,
            'BlueTeam' || LPAD(i::TEXT, 2, '0'),
            'WCComps_BlueTeam' || LPAD(i::TEXT, 2, '0')
        )
        ON CONFLICT (team_number) DO NOTHING;
    END LOOP;
END $$;

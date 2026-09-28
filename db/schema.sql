-- ============================================================
-- The Athlete Market — Roster Intelligence
-- PostgreSQL / Supabase schema (generated from app/models.py by scripts/gen_schema.py)
-- Safe to run on an empty database. Re-generate after changing models.
-- ============================================================

CREATE TABLE event_log (
	id SERIAL NOT NULL, 
	at TIMESTAMP WITH TIME ZONE NOT NULL, 
	level VARCHAR(10) NOT NULL, 
	event VARCHAR(60) NOT NULL, 
	sport VARCHAR(40), 
	entity_type VARCHAR(40), 
	entity_id INTEGER, 
	message TEXT NOT NULL, 
	data JSONB NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_event_log_at ON event_log (at);

CREATE INDEX ix_event_log_event ON event_log (event);

CREATE TABLE schools (
	id SERIAL NOT NULL, 
	slug VARCHAR(120) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	short_name VARCHAR(80), 
	division VARCHAR(40), 
	conference VARCHAR(120), 
	state VARCHAR(40), 
	athletics_domain VARCHAR(200), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (slug)
);

CREATE TABLE seasons (
	id SERIAL NOT NULL, 
	sport VARCHAR(40) NOT NULL, 
	label VARCHAR(20) NOT NULL, 
	start_year INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (sport, label)
);

CREATE TABLE telegram_channels (
	id SERIAL NOT NULL, 
	sport VARCHAR(40) NOT NULL, 
	title VARCHAR(120) NOT NULL, 
	channel_env_var VARCHAR(80) NOT NULL, 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (sport)
);

CREATE TABLE teams (
	id SERIAL NOT NULL, 
	school_id INTEGER NOT NULL, 
	sport VARCHAR(40) NOT NULL, 
	adapter VARCHAR(40) NOT NULL, 
	base_url VARCHAR(300) NOT NULL, 
	sport_path VARCHAR(80) NOT NULL, 
	active BOOLEAN NOT NULL, 
	notes TEXT, 
	PRIMARY KEY (id), 
	UNIQUE (school_id, sport), 
	FOREIGN KEY(school_id) REFERENCES schools (id) ON DELETE CASCADE
);

CREATE INDEX ix_teams_sport ON teams (sport);

CREATE TABLE opportunities (
	id SERIAL NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	sport VARCHAR(40) NOT NULL, 
	school_id INTEGER NOT NULL, 
	team_id INTEGER NOT NULL, 
	opportunity_type VARCHAR(30) NOT NULL, 
	position_group VARCHAR(20) NOT NULL, 
	position_label TEXT NOT NULL, 
	target_season VARCHAR(20) NOT NULL, 
	stats_season VARCHAR(20), 
	roster_season VARCHAR(20), 
	departure_basis VARCHAR(30), 
	signal FLOAT NOT NULL, 
	confidence VARCHAR(10) NOT NULL, 
	data_quality FLOAT, 
	components JSONB NOT NULL, 
	metrics JSONB NOT NULL, 
	reason TEXT, 
	evidence_hash VARCHAR(64), 
	status VARCHAR(20) NOT NULL, 
	status_note TEXT, 
	telegram_text TEXT, 
	telegram_text_edited BOOLEAN NOT NULL, 
	x_teaser TEXT, 
	low_confidence_override BOOLEAN NOT NULL, 
	first_detected_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_analyzed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_verified_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	source_updated_at TIMESTAMP WITH TIME ZONE, 
	approved_at TIMESTAMP WITH TIME ZONE, 
	scheduled_for DATE, 
	published_at TIMESTAMP WITH TIME ZONE, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (fingerprint), 
	FOREIGN KEY(school_id) REFERENCES schools (id), 
	FOREIGN KEY(team_id) REFERENCES teams (id)
);

CREATE INDEX ix_opp_sport_status ON opportunities (sport, status);

CREATE TABLE players (
	id SERIAL NOT NULL, 
	team_id INTEGER NOT NULL, 
	site_player_id VARCHAR(40), 
	full_name TEXT NOT NULL, 
	name_key VARCHAR(160) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (team_id, site_player_id), 
	FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE CASCADE
);

CREATE INDEX ix_players_name_key ON players (name_key);

CREATE INDEX ix_players_team_id ON players (team_id);

CREATE TABLE sources (
	id SERIAL NOT NULL, 
	team_id INTEGER, 
	url TEXT NOT NULL, 
	kind VARCHAR(40) NOT NULL, 
	tier VARCHAR(1) NOT NULL, 
	title TEXT, 
	publisher VARCHAR(200), 
	author_account VARCHAR(200), 
	season_label VARCHAR(20), 
	fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	http_status INTEGER, 
	available BOOLEAN NOT NULL, 
	content_hash VARCHAR(64), 
	error TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE SET NULL
);

CREATE INDEX ix_sources_team_id ON sources (team_id);

CREATE TABLE opportunity_evidence (
	id SERIAL NOT NULL, 
	opportunity_id INTEGER NOT NULL, 
	kind VARCHAR(30) NOT NULL, 
	label TEXT NOT NULL, 
	data JSONB NOT NULL, 
	source_id INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(opportunity_id) REFERENCES opportunities (id) ON DELETE CASCADE, 
	FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE SET NULL
);

CREATE INDEX ix_opportunity_evidence_opportunity_id ON opportunity_evidence (opportunity_id);

CREATE TABLE opportunity_sources (
	opportunity_id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	PRIMARY KEY (opportunity_id, source_id), 
	FOREIGN KEY(opportunity_id) REFERENCES opportunities (id) ON DELETE CASCADE, 
	FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE CASCADE
);

CREATE TABLE player_stats (
	id SERIAL NOT NULL, 
	team_id INTEGER NOT NULL, 
	season_id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	player_id INTEGER, 
	stat_type VARCHAR(30) NOT NULL, 
	name_raw TEXT NOT NULL, 
	jersey VARCHAR(16), 
	site_player_id VARCHAR(40), 
	stats JSONB NOT NULL, 
	raw JSONB NOT NULL, 
	collected_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE CASCADE, 
	FOREIGN KEY(season_id) REFERENCES seasons (id), 
	FOREIGN KEY(source_id) REFERENCES sources (id), 
	FOREIGN KEY(player_id) REFERENCES players (id) ON DELETE SET NULL
);

CREATE INDEX ix_player_stats_team_id ON player_stats (team_id);

CREATE TABLE published_posts (
	id SERIAL NOT NULL, 
	opportunity_id INTEGER NOT NULL, 
	sport VARCHAR(40) NOT NULL, 
	channel_ref VARCHAR(80) NOT NULL, 
	mode VARCHAR(10) NOT NULL, 
	telegram_message_id INTEGER, 
	text TEXT NOT NULL, 
	x_teaser TEXT, 
	status VARCHAR(20) NOT NULL, 
	error TEXT, 
	sent_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (opportunity_id, channel_ref, mode), 
	FOREIGN KEY(opportunity_id) REFERENCES opportunities (id) ON DELETE CASCADE
);

CREATE INDEX ix_published_posts_opportunity_id ON published_posts (opportunity_id);

CREATE TABLE publishing_queue (
	id SERIAL NOT NULL, 
	sport VARCHAR(40) NOT NULL, 
	publish_date DATE NOT NULL, 
	opportunity_id INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	note TEXT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (sport, publish_date), 
	FOREIGN KEY(opportunity_id) REFERENCES opportunities (id) ON DELETE CASCADE
);

CREATE TABLE roster_snapshots (
	id SERIAL NOT NULL, 
	team_id INTEGER NOT NULL, 
	season_id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	collected_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	player_count INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE CASCADE, 
	FOREIGN KEY(season_id) REFERENCES seasons (id), 
	FOREIGN KEY(source_id) REFERENCES sources (id)
);

CREATE INDEX ix_roster_snapshots_team_id ON roster_snapshots (team_id);

CREATE TABLE score_history (
	id SERIAL NOT NULL, 
	opportunity_id INTEGER NOT NULL, 
	at TIMESTAMP WITH TIME ZONE NOT NULL, 
	old_signal FLOAT, 
	new_signal FLOAT NOT NULL, 
	old_confidence VARCHAR(10), 
	new_confidence VARCHAR(10) NOT NULL, 
	reason TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(opportunity_id) REFERENCES opportunities (id) ON DELETE CASCADE
);

CREATE INDEX ix_score_history_opportunity_id ON score_history (opportunity_id);

CREATE TABLE roster_entries (
	id SERIAL NOT NULL, 
	snapshot_id INTEGER NOT NULL, 
	player_id INTEGER NOT NULL, 
	jersey VARCHAR(16), 
	position_raw TEXT, 
	position_group VARCHAR(20), 
	secondary_group VARCHAR(20), 
	position_confidence FLOAT, 
	is_two_way BOOLEAN NOT NULL, 
	class_year_raw TEXT, 
	class_year VARCHAR(10), 
	redshirt BOOLEAN, 
	eligibility_remaining INTEGER, 
	height TEXT, 
	weight TEXT, 
	bats VARCHAR(2), 
	throws VARCHAR(2), 
	hometown TEXT, 
	high_school TEXT, 
	previous_school TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(snapshot_id) REFERENCES roster_snapshots (id) ON DELETE CASCADE, 
	FOREIGN KEY(player_id) REFERENCES players (id) ON DELETE CASCADE
);

CREATE INDEX ix_roster_entries_snapshot_id ON roster_entries (snapshot_id);


-- Supabase: this app connects with the database password from the server only.
-- Enable Row Level Security with no policies so the public anon/REST API can't read or write these tables.
ALTER TABLE schools ENABLE ROW LEVEL SECURITY;
ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE seasons ENABLE ROW LEVEL SECURITY;
ALTER TABLE sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE roster_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE players ENABLE ROW LEVEL SECURITY;
ALTER TABLE roster_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE player_stats ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunity_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunity_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE score_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE telegram_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE publishing_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE published_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_log ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS metrics (
  entity TEXT NOT NULL,
  date TEXT NOT NULL,
  data TEXT NOT NULL,
  collected_at TEXT NOT NULL,
  PRIMARY KEY(entity, date)
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  entity TEXT NOT NULL,
  date TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  ready_at INTEGER NOT NULL DEFAULT 0,
  lease_until INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_due ON jobs(state, ready_at, lease_until);
CREATE INDEX IF NOT EXISTS jobs_entity_day ON jobs(entity, date);
CREATE TABLE IF NOT EXISTS parts (
  job_id TEXT NOT NULL,
  page_key TEXT NOT NULL,
  data TEXT NOT NULL,
  PRIMARY KEY(job_id, page_key)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

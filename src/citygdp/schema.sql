-- 城市 GDP 数据分析 —— 中间数据库 DDL
-- 设计说明见 DESIGN.md §5。本文件是 schema 的唯一定义处，db.py 直接执行。
--
-- 约定：
--   fact.value 一律为基本单位（本币元 / 人 / km² / 美元），缩放信息记在 note
--   fact 唯一键不含 source_id，在数据库层强制「一格一值」（DESIGN DD-10）

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS city (
  code         TEXT PRIMARY KEY,
  name_cn      TEXT NOT NULL,
  name_en      TEXT NOT NULL,
  country_iso3 TEXT NOT NULL,
  currency     TEXT NOT NULL,
  boundary     TEXT NOT NULL,
  pop_basis    TEXT NOT NULL,
  area_basis   TEXT NOT NULL,
  note         TEXT
);

CREATE TABLE IF NOT EXISTS source (
  id                 TEXT PRIMARY KEY,
  city_code          TEXT REFERENCES city(code),
  indicator          TEXT NOT NULL,
  organization       TEXT NOT NULL,
  dataset_title      TEXT NOT NULL,
  table_id           TEXT,
  url                TEXT NOT NULL,
  vintage            TEXT,
  published_at       TEXT,
  accessed_at        TEXT NOT NULL,
  http_etag          TEXT,
  http_last_modified TEXT,
  sha256             TEXT,
  local_path         TEXT,
  acquisition        TEXT NOT NULL CHECK (acquisition IN ('auto','manual')),
  notes              TEXT
);

CREATE TABLE IF NOT EXISTS fact (
  id          INTEGER PRIMARY KEY,
  source_id   TEXT NOT NULL REFERENCES source(id),
  entity_type TEXT NOT NULL CHECK (entity_type IN ('city','country','currency')),
  entity_code TEXT NOT NULL,
  indicator   TEXT NOT NULL CHECK (indicator IN (
                'gdp_lcu','gdp_real_lcu','population','area_km2',
                'country_gdp_usd','fx_lcu_per_usd')),
  year        INTEGER NOT NULL,
  value       REAL NOT NULL,
  unit        TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'final'
              CHECK (status IN ('final','preliminary','provisional')),
  note        TEXT,
  UNIQUE (entity_type, entity_code, indicator, year)
);

CREATE INDEX IF NOT EXISTS idx_fact_lookup
  ON fact(entity_code, indicator, year);

CREATE TABLE IF NOT EXISTS derived (
  city_code   TEXT NOT NULL REFERENCES city(code),
  year        INTEGER NOT NULL,
  metric      TEXT NOT NULL CHECK (metric IN (
                'gdp_usd','primacy_pct','gdp_per_capita_usd','gdp_per_km2_usd')),
  value       REAL,
  unit        TEXT NOT NULL,
  formula     TEXT NOT NULL,
  inputs_json TEXT NOT NULL,
  computed_at TEXT NOT NULL,
  PRIMARY KEY (city_code, year, metric)
);

CREATE TABLE IF NOT EXISTS issue (
  id         INTEGER PRIMARY KEY,
  step       TEXT,
  city_code  TEXT,
  year       INTEGER,
  metric     TEXT,
  severity   TEXT NOT NULL CHECK (severity IN ('info','warn','error')),
  message    TEXT NOT NULL,
  created_at TEXT NOT NULL
);

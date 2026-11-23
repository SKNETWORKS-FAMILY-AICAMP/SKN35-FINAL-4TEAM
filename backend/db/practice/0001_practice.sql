-- =====================================================================
-- SlotAgent 1.2 연습 DB (PostgreSQL 16, 제품 DB 와 별도 인스턴스)
-- 에이전트가 시험 중에 읽기 도구로 조회하는 업무 데이터 (에러 지표·장애 기록 등).
-- 평가팩 버전마다 스키마 하나. 데이터를 넣은 뒤 동결한다.
--
--   meta                     스키마 목록·동결·내용 해시 (에이전트에게 안 보임)
--   pack_it_ops_v1_0         IT 운영 평가팩 v1.0                            [8주]
--   pack_data_pilot_v0_1     데이터 분석 파일럿                              [8주, Should]
--   pack_cs_v1_0             고객지원                                        [8주 뒤, OOS-03]
--
-- 읽기 도구가 이 DB 에 어떻게 붙는지(실제 DB MCP 서버 / 플랫폼 연습 도구)는 설계 결정 D-05.
-- 어느 쪽이든 에이전트 역할은 읽기 전용이다.
-- 제품 DB 와의 연결: data_snapshots(source_kind='db_schema').location     = meta.pack_schemas.schema_name
--                   data_snapshots.content_hash                          = meta.pack_schemas.content_hash
-- (서로 다른 인스턴스라 FK 는 없음. 동결 때와 실험 시작 전 해시 대조로 확인)
-- =====================================================================

-- 역할: 빌더(데이터 넣기), 에이전트 읽기 전용(읽기 도구가 이 역할로 접속)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pack_builder') THEN
    CREATE ROLE pack_builder NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_reader') THEN
    CREATE ROLE agent_reader NOLOGIN; END IF;
END $$;
-- 에이전트 연결은 항상 읽기 전용 트랜잭션. 쓰기 SQL 은 실패하고, 금지 행동 채점은 span 으로
ALTER ROLE agent_reader SET default_transaction_read_only = on;
-- 무거운 조회로 DB 를 붙잡지 못하게: 한 문장 5초, 열어 둔 트랜잭션 30초, 정렬·해시 메모리 16MB.
-- 돌려주는 행 수 상한(예: 500행)은 읽기 도구(앱)가 LIMIT 으로 지킴
ALTER ROLE agent_reader SET statement_timeout = '5s';
ALTER ROLE agent_reader SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE agent_reader SET work_mem = '16MB';

CREATE SCHEMA IF NOT EXISTS meta;
REVOKE ALL ON SCHEMA meta FROM PUBLIC;

CREATE TABLE IF NOT EXISTS meta.pack_schemas (
  schema_name   text PRIMARY KEY,                -- pack_it_ops_v1_0
  pack_code     text NOT NULL,                   -- it_ops_github
  pack_version  text NOT NULL,                   -- v1.0
  domain_code   text NOT NULL,                   -- it_ops
  content_hash  text,                            -- 데이터 해시 (= 제품 DB data_snapshots.content_hash)
  structure_hash text,                           -- 구조 해시 (칸·타입·제약·인덱스)
  frozen_at     timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (pack_code, pack_version),
  CHECK ((frozen_at IS NULL) = (content_hash IS NULL)),
  CHECK ((frozen_at IS NULL) = (structure_hash IS NULL))
);

-- 데이터 해시: 테이블마다 모든 행을 글자로 바꿔 정렬한 뒤 md5, 테이블 이름과 함께 다시 md5.
-- 행을 글자로 바꾸는 결과가 세션 설정(시간대·날짜 형식·실수 자릿수)에 따라 달라지지 않게 함수 안에서 고정
CREATE OR REPLACE FUNCTION meta.data_hash(p_schema text) RETURNS text
LANGUAGE plpgsql STABLE
SET TimeZone = 'GMT' SET DateStyle = 'ISO, YMD' SET IntervalStyle = 'postgres' SET extra_float_digits = 3
AS $$
DECLARE t record; acc text := ''; h text;
BEGIN
  FOR t IN SELECT table_name FROM information_schema.tables
           WHERE table_schema = p_schema AND table_type = 'BASE TABLE' ORDER BY table_name LOOP
    EXECUTE format(
      'SELECT coalesce(md5(string_agg(r::text, %L ORDER BY r::text COLLATE "C")), %L) FROM %I.%I r',
      E'\n', 'empty', p_schema, t.table_name) INTO h;
    acc := acc || t.table_name || ':' || h || ';';
  END LOOP;
  RETURN md5(acc);
END $$;

-- 구조 해시: 칸(이름·타입·필수·기본값) + 제약(PK·FK·UNIQUE·CHECK) + 인덱스. 행 트리거를 피해 가는 ALTER TABLE 도 잡음
CREATE OR REPLACE FUNCTION meta.structure_hash(p_schema text) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT md5(
    coalesce((SELECT string_agg(format('%s.%s:%s:%s:%s', c.relname, a.attname, format_type(a.atttypid, a.atttypmod),
                                       a.attnotnull, pg_get_expr(d.adbin, d.adrelid)), ';' ORDER BY c.relname, a.attnum)
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
                LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
               WHERE n.nspname = p_schema AND c.relkind = 'r'), '') || '|' ||
    coalesce((SELECT string_agg(format('%s:%s', c.relname, pg_get_constraintdef(k.oid)), ';' ORDER BY c.relname, pg_get_constraintdef(k.oid))
                FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = p_schema), '') || '|' ||
    coalesce((SELECT string_agg(regexp_replace(indexdef, ' INDEX \S+ ON ', ' INDEX ON '), ';' ORDER BY indexdef)
                FROM pg_indexes WHERE schemaname = p_schema), ''))
$$;

-- 동결: 데이터·구조 해시 기록 + 빌더 쓰기 권한 회수 + 에이전트 읽기 권한 부여
CREATE OR REPLACE FUNCTION meta.freeze_pack(p_schema text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE h text;
BEGIN
  IF (SELECT frozen_at FROM meta.pack_schemas WHERE schema_name = p_schema) IS NOT NULL THEN
    RAISE EXCEPTION '% 은(는) 이미 동결됐습니다', p_schema;
  END IF;
  h := meta.data_hash(p_schema);
  UPDATE meta.pack_schemas SET content_hash = h, structure_hash = meta.structure_hash(p_schema), frozen_at = now()
   WHERE schema_name = p_schema;
  EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA %I FROM pack_builder', p_schema);
  EXECUTE format('GRANT USAGE ON SCHEMA %I TO agent_reader', p_schema);
  EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO agent_reader', p_schema);
  RETURN h;
END $$;

-- 동결된 스키마가 바뀌지 않았는지 확인 (실험 시작 전, 매일). 데이터와 구조 둘 다 같아야 true
CREATE OR REPLACE FUNCTION meta.verify_pack(p_schema text) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT content_hash = meta.data_hash(p_schema) AND structure_hash = meta.structure_hash(p_schema)
    FROM meta.pack_schemas WHERE schema_name = p_schema;
$$;

-- 동결된 스키마는 소유자 권한으로도 못 바꾸게 테이블마다 트리거
CREATE OR REPLACE FUNCTION meta.trg_frozen_pack() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT frozen_at FROM meta.pack_schemas WHERE schema_name = TG_TABLE_SCHEMA) IS NOT NULL THEN
    RAISE EXCEPTION '테스트 데이터 %.%은(는) 동결됐습니다: 새 평가팩 버전 스키마를 만드세요', TG_TABLE_SCHEMA, TG_TABLE_NAME;
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;

-- 새 평가팩 버전 스키마에 동결 트리거를 거는 도우미
CREATE OR REPLACE FUNCTION meta.attach_freeze_triggers(p_schema text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE t record;
BEGIN
  FOR t IN SELECT table_name FROM information_schema.tables
           WHERE table_schema = p_schema AND table_type = 'BASE TABLE' LOOP
    EXECUTE format('CREATE TRIGGER frozen BEFORE INSERT OR UPDATE OR DELETE ON %I.%I
                    FOR EACH ROW EXECUTE FUNCTION meta.trg_frozen_pack()', p_schema, t.table_name);
  END LOOP;
END $$;

-- ---------------------------------------------------------------------
-- IT 운영 평가팩 v1.0: DB 조회 도구(db.query_errors 등)가 읽는 운영 지표
-- ---------------------------------------------------------------------
INSERT INTO meta.pack_schemas(schema_name, pack_code, pack_version, domain_code)
VALUES ('pack_it_ops_v1_0', 'it_ops_github', 'v1.0', 'it_ops')
ON CONFLICT DO NOTHING;

CREATE SCHEMA IF NOT EXISTS pack_it_ops_v1_0;

CREATE TABLE pack_it_ops_v1_0.services (
  name          text PRIMARY KEY,               -- api / web / worker
  owner_team    text,
  repo          text                            -- 연결된 GitHub 테스트 저장소
);

CREATE TABLE pack_it_ops_v1_0.error_counts (     -- 시간당 에러 수 (배포 전후 비교 과제)
  service       text NOT NULL REFERENCES pack_it_ops_v1_0.services(name),
  hour          timestamptz NOT NULL,
  count         int NOT NULL CHECK (count >= 0),
  PRIMARY KEY (service, hour)
);

CREATE TABLE pack_it_ops_v1_0.incidents (        -- 장애 기록 (장애와 이슈 연결 과제)
  id            int PRIMARY KEY,
  service       text NOT NULL REFERENCES pack_it_ops_v1_0.services(name),
  started_at    timestamptz NOT NULL,
  resolved_at   timestamptz,
  severity      text,                           -- 약어·빈 값 일부러 섞음
  issue_ref     text                            -- "repo#142" 형태, 빈 값 허용
);

SELECT meta.attach_freeze_triggers('pack_it_ops_v1_0');

"""[② 평가팩] packs/<code>/<version>/ 파일을 읽어 DB에 넣고, 검사하고, 잠근다.

쓰는 테이블: pack_versions, data_snapshots, templates, tasks, answer_conditions, golden_trajectories, env_checks
넘겨주는 것: 잠긴 pack_version_id (pack_versions.status = locked)
지킬 것: answer_conditions.spec 은 contracts.validate("answer_condition", spec, part=kind)
          골든 궤적은 trace 스키마 → ①의 규칙 채점 테스트에 그대로 씀
"""

# 평가팩 원본 (② 담당)

`packs/<pack_code>/<version>/pack.json` — 모양은 `contracts/examples/pack.json` 과 같음.
DB에는 `slotagent.packs.loader.load_pack()` 으로 넣고, 잠근 뒤에는 이 폴더도 고치지 않음 (새 버전 폴더를 만듦).

- 고칠 때 쓰는 문항과 확인용 문항은 **문항 유형(template) 단위로** 나눔: pack.json 의 `templates[].split` = `dev` / `held` → DB `templates.split` (0003).
  실험 ⑪에서 시험 맞춤이 섞였던 문제. 같은 유형의 문항이 양쪽에 섞이지 않게 유형 단위로 나눔. plan-proposal 은 기본으로 held 만 고름
- 정답 조건마다 `gate`(성공 판정에 쓰는지). 비우면 kind 별 기본값: info·order·forbidden·end_state = true, link = false
- 저장 전 검사: `contracts.validate("answer_condition", spec, part=kind)` + `common.checks.check_task_conditions(conditions)` (link.supports 가 같은 문항 info key 인지 등)
- 골든 궤적은 `golden/<template>.<kind>.json` (trace 스키마)

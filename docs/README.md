# 설계 문서

- 설계로 넘긴 것 D-01~D-14 (요구사항 정의서 1.2 시트) — 결정하면 `docs/decisions/D-xx.md` 로 한 장씩
- 팀이 정해야 하는 것 (뼈대의 임시 값): `decisions_pending.md` (P-01~P-10)
- 11/22 뼈대 검토 39개 처리 기록: `review_1122.md`
- 기준 문서: SlotAgent 1.2 기획서, ERD·DB 설계서 v1.2, 역할 나누기 v1

## ② 평가팩 현재 자료

- [평가팩 안내](../packs/README.md): 현재 수량·구현/검증 경계
- [전체 문항 목록](../packs/QUESTIONS.md): pack.json에서 자동 생성하는 유일한 상세 문항 목록
- [① 전달 문서](role2_handoff_20261124.md): 서버·DB·잠금 연동 확인 사항
- [P-05 계약](P05_confirmation_handoff.md): 승인 정책과 저장/실행 경계
- [오답 위험 예측](../backend/ml_failure_risk/README.md): 전처리·교차검증·LightGBM 선정·최종 평가1회 및11/27 사람 검수100건 완료. 자동 라벨과99/100 일치, 정답49·오답51. 현재 평가팩과 별개의 사전 실험 데이터이며 제품 판정기 검증은 아님

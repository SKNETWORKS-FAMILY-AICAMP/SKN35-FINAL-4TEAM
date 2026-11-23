# 추가 템플릿 10개 / 문항 30개

모두 개발용 합성 데이터이며 실제 모델 성능 검증 전이다.

### DEPLOY_FAILURES_PERIOD-001
acme/payment-service의 production 환경에서 종료된 실패 배포 ID를 2026-11-16 00:00 이상, 11-17 00:00 미만(KST) 범위로 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"run_ids": ["101", "105"]}`

### DEPLOY_FAILURES_PERIOD-002
acme/catalog-service의 production 환경에서 종료된 실패 배포 ID를 2026-11-16 00:00 이상, 11-17 00:00 미만(KST) 범위로 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"run_ids": ["201", "205"]}`

### DEPLOY_FAILURES_PERIOD-003
acme/auth-service의 production 환경에서 종료된 실패 배포 ID를 2026-11-16 00:00 이상, 11-17 00:00 미만(KST) 범위로 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"run_ids": ["301", "305"]}`

### DEPLOY_SLOW_RUNS-001
acme/payment-service production 전체 배포 기록에서 성공 여부와 무관하게 시작부터 종료까지 600초를 초과한 배포 ID를 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"run_ids": ["103"]}`

### DEPLOY_SLOW_RUNS-002
acme/catalog-service production 전체 배포 기록에서 성공 여부와 무관하게 시작부터 종료까지 300초를 초과한 배포 ID를 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"run_ids": ["201", "203", "205"]}`

### DEPLOY_SLOW_RUNS-003
acme/auth-service staging 전체 배포 기록에서 성공 여부와 무관하게 시작부터 종료까지 180초를 초과한 배포 ID를 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"run_ids": []}`

### DEPLOY_DAILY_COUNTS-001
acme/payment-service production에서 2026-11-16(KST)에 종료된 배포의 성공 건수와 실패 건수를 각각 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"success_count": 2, "failure_count": 2}`

### DEPLOY_DAILY_COUNTS-002
acme/catalog-service production에서 2026-11-16(KST)에 종료된 배포의 성공 건수와 실패 건수를 각각 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"success_count": 2, "failure_count": 2}`

### DEPLOY_DAILY_COUNTS-003
acme/auth-service staging에서 2026-11-16(KST)에 종료된 배포의 성공 건수와 실패 건수를 각각 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"success_count": 1, "failure_count": 0}`

### DEPLOY_RECOVERY-001
acme/payment-service production 배포 101의 실패 종료 후, 가장 먼저 성공 종료한 배포 ID를 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"run_ids": ["102"]}`

### DEPLOY_RECOVERY-002
acme/catalog-service production 배포 201의 실패 종료 후, 가장 먼저 성공 종료한 배포 ID를 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"run_ids": ["202"]}`

### DEPLOY_RECOVERY-003
acme/auth-service production 배포 301의 실패 종료 후, 가장 먼저 성공 종료한 배포 ID를 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"run_ids": ["302"]}`

### DEPLOY_ENV_COMPARE-001
acme/payment-service의 production과 staging에서 각각 가장 최근에 성공 종료한 배포 버전을 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"production_version": "v2.1.0", "staging_version": "v3.1.0-rc1"}`

### DEPLOY_ENV_COMPARE-002
acme/catalog-service의 production과 staging에서 각각 가장 최근에 성공 종료한 배포 버전을 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"production_version": "v2.2.0", "staging_version": "v3.2.0-rc1"}`

### DEPLOY_ENV_COMPARE-003
acme/auth-service의 production과 staging에서 각각 가장 최근에 성공 종료한 배포 버전을 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"production_version": "v2.3.0", "staging_version": "v3.3.0-rc1"}`

### ISSUES_ASSIGNED_OPEN-001
acme/payment-service에서 mina에게 배정된 열린 이슈 번호를 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"issue_ids": ["101"]}`

### ISSUES_ASSIGNED_OPEN-002
acme/catalog-service에서 jun에게 배정된 열린 이슈 번호를 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"issue_ids": ["205"]}`

### ISSUES_ASSIGNED_OPEN-003
acme/auth-service에서 nobody에게 배정된 열린 이슈 번호를 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"issue_ids": []}`

### ISSUES_STALE_UNASSIGNED-001
acme/payment-service에서 열린 미배정 이슈 중 마지막 갱신이 2026-11-10T00:00:00+09:00보다 이전인 이슈 번호를 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"issue_ids": ["102"]}`

### ISSUES_STALE_UNASSIGNED-002
acme/catalog-service에서 열린 미배정 이슈 중 마지막 갱신이 2026-11-11T00:00:00+09:00보다 이전인 이슈 번호를 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"issue_ids": ["202", "204"]}`

### ISSUES_STALE_UNASSIGNED-003
acme/auth-service에서 열린 미배정 이슈 중 마지막 갱신이 2026-11-01T00:00:00+09:00보다 이전인 이슈 번호를 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"issue_ids": []}`

### ISSUES_CLOSED_PERIOD-001
acme/payment-service의 닫힌 이슈 번호를 2026-11-16 00:00 이상, 11-17 00:00 미만(KST) 범위로 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"issue_ids": ["103"]}`

### ISSUES_CLOSED_PERIOD-002
acme/catalog-service의 닫힌 이슈 번호를 2026-11-16 00:00 이상, 11-17 00:00 미만(KST) 범위로 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"issue_ids": ["203"]}`

### ISSUES_CLOSED_PERIOD-003
acme/auth-service의 닫힌 이슈 번호를 2026-11-16 00:00 이상, 11-17 00:00 미만(KST) 범위로 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"issue_ids": ["303"]}`

### ISSUES_LABEL_COUNTS-001
acme/payment-service의 열린 이슈 중 bug와 urgent 라벨의 건수를 각각 알려 줘. 둘 다 붙었으면 양쪽에 각각 세어 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"bug_count": 2, "urgent_count": 2}`

### ISSUES_LABEL_COUNTS-002
acme/catalog-service의 열린 이슈 중 bug와 urgent 라벨의 건수를 각각 알려 줘. 둘 다 붙었으면 양쪽에 각각 세어 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"bug_count": 2, "urgent_count": 2}`

### ISSUES_LABEL_COUNTS-003
acme/auth-service의 열린 이슈 중 bug와 urgent 라벨의 건수를 각각 알려 줘. 둘 다 붙었으면 양쪽에 각각 세어 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"bug_count": 2, "urgent_count": 2}`

### DEPLOY_RELEASE_LINK-001
acme/payment-service production의 가장 최근 성공 배포를 찾고, 같은 저장소에서 배포 커밋 SHA가 일치하는 릴리스 태그를 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"release_tag": "v2.1.0"}`

### DEPLOY_RELEASE_LINK-002
acme/catalog-service production의 가장 최근 성공 배포를 찾고, 같은 저장소에서 배포 커밋 SHA가 일치하는 릴리스 태그를 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"release_tag": "v2.2.0"}`

### DEPLOY_RELEASE_LINK-003
acme/auth-service staging의 가장 최근 성공 배포를 찾고, 같은 저장소에서 배포 커밋 SHA가 일치하는 릴리스 태그를 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"release_tag": "v3.3.0-rc1"}`


가짜 실행 연결 완료: 전체 12개 유형·38문항에서 5개 시나리오씩 190건을 검사한다. 결과는 `tmp/deployment-smoke/summary.json`에 저장한다. 실제 LLM·① 제품 엔진 검증은 별도다.

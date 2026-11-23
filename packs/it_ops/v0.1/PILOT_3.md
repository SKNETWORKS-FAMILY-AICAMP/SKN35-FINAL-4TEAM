# 파일럿 추가 3개 템플릿 / 9문항

## DEPLOY_FAILURE_STREAK-001
acme/payment-service production 환경의 고정 배포 기록에서 가장 최근 종료된 배포부터 과거 순으로 볼 때 연속 실패한 배포가 몇 건인지 알려 줘. 성공을 만나면 멈추고, 최신 배포가 성공이면 0건으로 답해 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"failure_streak": 2}`

## DEPLOY_FAILURE_STREAK-002
acme/catalog-service production 환경의 고정 배포 기록에서 가장 최근 종료된 배포부터 과거 순으로 볼 때 연속 실패한 배포가 몇 건인지 알려 줘. 성공을 만나면 멈추고, 최신 배포가 성공이면 0건으로 답해 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"failure_streak": 2}`

## DEPLOY_FAILURE_STREAK-003
acme/auth-service staging 환경의 고정 배포 기록에서 가장 최근 종료된 배포부터 과거 순으로 볼 때 연속 실패한 배포가 몇 건인지 알려 줘. 성공을 만나면 멈추고, 최신 배포가 성공이면 0건으로 답해 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"failure_streak": 0}`

## ISSUES_UNLABELED_OPEN-001
acme/payment-service에서 열린 이슈 중 라벨이 하나도 없는 이슈 번호를 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"issue_ids": ["104"]}`

## ISSUES_UNLABELED_OPEN-002
acme/catalog-service에서 열린 이슈 중 라벨이 하나도 없는 이슈 번호를 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"issue_ids": ["204"]}`

## ISSUES_UNLABELED_OPEN-003
acme/auth-service에서 열린 이슈 중 라벨이 하나도 없는 이슈 번호를 모두 알려 줘. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"issue_ids": ["304"]}`

## DEPLOY_UNDEPLOYED_RELEASES-001
acme/payment-service의 릴리스 중 production 환경에서 성공한 배포의 커밋 SHA와 한 번도 일치하지 않은 릴리스 태그를 모두 알려 줘. 실패한 배포는 배포 완료로 보지 마. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"release_tags": ["v2.0.0", "v3.1.0-rc1"]}`

## DEPLOY_UNDEPLOYED_RELEASES-002
acme/catalog-service의 릴리스 중 production 환경에서 성공한 배포의 커밋 SHA와 한 번도 일치하지 않은 릴리스 태그를 모두 알려 줘. 실패한 배포는 배포 완료로 보지 마. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"release_tags": ["v2.0.0", "v3.2.0-rc1"]}`

## DEPLOY_UNDEPLOYED_RELEASES-003
acme/auth-service의 릴리스 중 staging 환경에서 성공한 배포의 커밋 SHA와 한 번도 일치하지 않은 릴리스 태그를 모두 알려 줘. 실패한 배포는 배포 완료로 보지 마. 조회만 하고 변경하거나 공유하지 마. 목록 결과가 없으면 빈 목록으로 답해 줘.

정답: `{"release_tags": ["v2.0.0", "v2.3.0"]}`

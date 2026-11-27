# P-03 연습 MCP 서버 안내

11/27 후속 환경 점검: [environment_review.json](environment_review.json)에5도구의 응답 경계·13개 데이터 설계 기록·전체152문항의 노출 위험을 기록했다. 결과 암시 scenario_id15문항과 도구 성공 보장3문항을 수정해 해당 패턴은0건이다. [수정·해시·검증 기록](prompt_revision_1127.json)과 [검토 내용](../REVIEW_CHECKLIST.md)을 참고한다. 변경된 scenarios/evidence는 현재 Docker의3개 마운트 원본에 포함되지 않으므로 서버 이미지0.1.1은 유지한다. 실제 MCP 범위는8유형26문항이며 나머지42유형의 환경 완료를 뜻하지 않는다. DB `sa_env_checks` 승인·팩 잠금·독립 검수는 수행하지 않았다.

현재 **GitHub 합성 조회 서버0.1.1 구현·로컬 Docker 빌드·stdio 통신38호출 검증 완료(11/27)** 상태다. 단일 평가팩 안의 조회 그룹8유형·26문항을 지원하는 도구5개를 제공한다. 전체50유형 중 나머지42유형의 Slack 쓰기/DB 조회/장애 전용 도구는 이 서버에 아직 없다.

지원 범위는 servers.json의 template_codes로 명시한다. 통합 팩50유형 전체를 지원한다고 간주하지 않는다. 기존 실제 통신 검증 결과는 조회 그룹에만 적용된다.

## 서버와 데이터

[ab_plan.json](ab_plan.json)은 실제 서버 지원8유형26문항의 A(전체5도구)/B(동일 기능3도구) 비교 준비안이다. `scripts/prepare_practice_ab.py`로 재생성하며 자동 실행·등록·과금은 하지 않는다. candidate_specs는 모델 입력용 도구 정의를 포함한 agent_spec, worker_stdio는 운영자만 쓰는 Docker 설정이다. worker_stdio를 파일로 분리하면 eng_serve.load_stdio로 읽을 수 있고 arguments=[]로 이미지의 ENTRYPOINT를 그대로 사용한다. 고정된 로컬 이미지이므로 다른 PC에서는 동일 빌드·이미지 ID·데이터 경로를 검증해야 한다. 모델 버전·가격·예산·reps·형식 정책·근거 관문·DB 승인 확정 전 성능 결과로 사용하지 않는다.

추가 공개 경계 점검: MCP 미지원42유형의 로컬 정상 경로126문항·조회 응답190개를 검사했고 비공개 fixture 키와 JSON 해석 오류 검출은0건이었다. [local_boundary_review.json](local_boundary_review.json)에 문항별 결과를 보존한다. 이는 실제 서비스 연결 검증이 아니다. 문항 문자열 겹침29건은 정상 규격/입력과 구분했고, 절차 안내5유형15문항은 업무 제약과 풀이 힌트가 섞였는지 독립 검토할 대상으로 남겼다. 결과 암시ID·미래 성공 보장18문항의 수정 후 패턴 검출은0건이다.

실행 명세는 servers.json, 실제 확인 결과는 verification.json이다. status=ready와 image/command가 채워져 있다. 명세는 현재 팩의 독립 파일이며 공식 pack_version 저장 계약/DB 칼럼으로 편입하는 방식은 ① 검토 대기다.

| 도구 | 기능 | 데이터 |
|---|---|---|
| list_deployments | github.actions.read | deployments.json + operations.json의 runs. 실행 번호는 정수 run_id |
| list_issues | github.issues.read | issues.json + operations.json의 issues. 이슈 번호는 문자열 number |
| list_operation_runs | github.actions.read | 위 배포 전체와 같은 범위. 실행 번호는 문자열 id |
| list_operation_issues | github.issues.read | 위 이슈 전체와 같은 범위. 이슈 번호는 문자열 id |
| list_operation_releases | github.releases.read | operations.json의 releases |

repo 문자열을 생략하면 전체, 지정하면 정확 일치, 없으면 빈 배열이다. 각 도구의 기존 원본 순서를 유지하고 다른 원본의 기록을 뒤에 추가한다. repo 외 필터·정렬은 반환 레코드에서 수행한다. 기존 필드·번호 타입은 유지하며 원본에 있는 sha/started_at/updated_at/closed_at은 두 경로 모두 제공한다. 원본에 없는 필드는 생성하지 않는다. 같은 repo·번호가 두 원본에 중복되면 서버 시작을 거절한다. 도구별 입력·디코딩한 출력 JSON Schema는 명세에 있다. 공식 GitHub MCP 도구의 모든 세부 동작을 재현했다는 뜻은 아니다.

11/27 수정 전에는 배포·이슈 도구가 ops/other와 payment/catalog/auth로 나뉜 데이터를 제공하면서 설명은 동일했다. 26문항 중23문항에서 다른 쪽 조회 도구 선택 시 빈 결과가 재현됐다. 0.1.1은 전체 배포24건·이슈28건을 각 대응 경로에서 제공하며, 릴리스는 기존9건을 유지한다. 고정 원본3개와 pack.json·정답·골든은 수정하지 않았다. 정적 검사는 지원26문항의 각 필요 기능별 대응 도구가 해당 저장소 기록을 제공하는지 추가로 확인한다. 이는 정답 도출 가능성 전체의 증명이나 실제 모델16풀이 재검증은 아니다.

원본3개는 팩의 data/에 있으며 컨테이너의 /data/<파일명>으로 읽기 전용 마운트한다. snapshot_version과 common.canonical_hash(JSON)를 명세와 비교해 서버 시작 시 검증한다. 키 순서·개행 변경은 무관하고 값 변경은 실패한다. 시작 후에는 검증된 메모리 스냅샷을 읽는다.

팩 전체·pack.json·reference·golden·검수표·문항 목록을 마운트하지 않는다. 이미지는 서버 코드·해시 함수·명세만 포함하며 데이터는 외부 마운트한다.

## 빌드와 실제 검증

```powershell
docker build -t slotagent-it-ops-practice:0.1.1 -f packs/it_ops/v0.1/practice/Dockerfile .
backend/.venv/Scripts/python.exe packs/it_ops/v0.1/practice/check_mcp.py --docker-image slotagent-it-ops-practice:0.1.1
backend/.venv/Scripts/python.exe packs/it_ops/v0.1/reference/verify_practice.py --require-launchable
```

확인한 이미지 ID는 servers.json에 있다. **로컬 Docker 이미지이며 레지스트리 미게시**다. 다른 PC에서는 빌드하고 그 PC의 불변 image ID를 고정해야 한다. Python base digest·직접 의존성 버전은 고정했지만 간접 의존성까지 완전히 고정한 재빌드 일치는 보장하지 않는다.

command는 전체 argv다. 엔진은 Docker --entrypoint=command[0]로 지정하고 나머지를 컨테이너 인자로 넘길 수 있다. 이미지 기본 ENTRYPOINT도 같은 서버를 실행하므로 check_mcp는 이미지 자체를 실행한다.

실제 검증은 initialize/tools/list/resources/read 및 도구5개의 전체·모든 지원 저장소별 필터·빈결과·잘못된인자38호출이다. 설명·입력 스키마·버전·고정 데이터 해시도 확인했다. network=none·read-only root·비root·cap-drop=ALL로 확인했다. 데이터 읽기 권한만 제공한다. Windows 로컬 subprocess는 기존 응답 대기 이력이 있어 Docker 경로를 실행 검증 기준으로 사용했다. 이전0.1.0/20호출 이력은 verification.json의 previous_verification에 보존한다.

verify_practice는 명세·파일의 로컬 정합성만 검사하며 실제 컨테이너를 띄우지 않는다. 그 결과 actual_mcp_verified=false는 이 정적 검사 자체가 실통신을 확인하지 않는다는 뜻이다. 실제 MCP 통신 증거는 verification.json/check_mcp 보고서다.

## MCP 응답과 시작 검사

도구 결과는 MCP TextContent 안 JSON 배열이다. structuredContent는 사용하지 않는다. 인자 오류는 isError=true다. 메타데이터는 도구를 추가하지 않고 resources/read의 slotagent://practice/manifest에서 제공한다. version/data_version/snapshot_hashes/도구·input_schema·decoded_output_schema를 반환한다.

①은 새 trial/attempt마다 새 컨테이너를 띄우고 종료 후 제거해야 한다. 데이터 버전/해시·도구 목록·스키마·접속을 검사해 sa_env_checks에 기록하고 불일치하면 실행하지 않는다. 그 제품 수명주기 구현과 기록 저장은 아직 통합 검증하지 않았다.

후보 서버↔연습 서버 매핑에서 후보 도구의 차이를 같은 구현으로 지우지 않도록 ①②가 확인해야 한다. 공식 실행 명세 저장 위치·metadata 규약·어댑터 버전 기록도 [① 전달 문서](../../../../docs/role2_handoff_20261124.md)의 확인 요청이다. P-05 정책/DB 결정은 별도 문서를 따른다.

2026-11-24 비중 재편: 서버 도구5개·원본3개는 유지하고 호스트 manifest의 활성 template_codes를8유형으로 축소했다. 이전15유형 기준 실통신 검증 기록은 이력이며 이번에 컨테이너를 재실행한 것은 아니다. 나머지42유형의 로컬 조회/쓰기/장애 어댑터를 이 서버가 지원한다고 간주하지 않는다.

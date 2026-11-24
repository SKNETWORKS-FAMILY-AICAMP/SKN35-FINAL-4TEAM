# P-03 연습 MCP 서버 안내

현재 **GitHub 합성 조회 서버 구현·로컬 Docker 빌드·stdio 통신 검증 완료** 상태다. 단일 평가팩 안의 조회 그룹15유형·47문항을 지원하는 도구5개를 제공한다. 전체42유형 중 나머지27유형의 Slack 쓰기/DB 조회/장애 전용 도구는 이 서버에 아직 없다.

지원 범위는 servers.json의 template_codes로 명시한다. 통합 팩42유형 전체를 지원한다고 간주하지 않는다. 기존 실제 통신 검증 결과는 조회 그룹에만 적용된다.

## 서버와 데이터

실행 명세는 servers.json, 실제 확인 결과는 verification.json이다. status=ready와 image/command가 채워져 있다. 명세는 현재 팩의 독립 파일이며 공식 pack_version 저장 계약/DB 칼럼으로 편입하는 방식은 ① 검토 대기다.

| 도구 | 기능 | 데이터 |
|---|---|---|
| list_deployments | github.actions.read | deployments.json |
| list_issues | github.issues.read | issues.json |
| list_operation_runs | github.actions.read | operations.json의 runs |
| list_operation_issues | github.issues.read | operations.json의 issues |
| list_operation_releases | github.releases.read | operations.json의 releases |

repo 문자열을 생략하면 전체, 지정하면 정확 일치, 없으면 빈 배열이다. 원본 배열 순서를 유지한다. 도구별 입력·디코딩한 출력 JSON Schema는 명세에 있다. 공식 GitHub MCP 도구의 모든 세부 동작을 재현했다는 뜻은 아니다. run_id 정수/id 문자열, 이슈 number/id 등 도구별 레코드 차이가 있어 이름표만으로 호환을 판단하지 않는다.

원본3개는 팩의 data/에 있으며 컨테이너의 /data/<파일명>으로 읽기 전용 마운트한다. snapshot_version과 common.canonical_hash(JSON)를 명세와 비교해 서버 시작 시 검증한다. 키 순서·개행 변경은 무관하고 값 변경은 실패한다. 시작 후에는 검증된 메모리 스냅샷을 읽는다.

팩 전체·pack.json·reference·golden·검수표·문항 목록을 마운트하지 않는다. 이미지는 서버 코드·해시 함수·명세만 포함하며 데이터는 외부 마운트한다.

## 빌드와 실제 검증

```powershell
docker build -t slotagent-it-ops-practice:0.1.0 -f packs/it_ops/v0.1/practice/Dockerfile .
.venv/Scripts/python.exe packs/it_ops/v0.1/practice/check_mcp.py --docker-image slotagent-it-ops-practice:0.1.0
.venv/Scripts/python.exe packs/it_ops/v0.1/reference/verify_practice.py --require-launchable
```

확인한 이미지 ID는 servers.json에 있다. **로컬 Docker 이미지이며 레지스트리 미게시**다. 다른 PC에서는 빌드하고 그 PC의 불변 image ID를 고정해야 한다. Python base digest·직접 의존성 버전은 고정했지만 간접 의존성까지 완전히 고정한 재빌드 일치는 보장하지 않는다.

command는 전체 argv다. 엔진은 Docker --entrypoint=command[0]로 지정하고 나머지를 컨테이너 인자로 넘길 수 있다. 이미지 기본 ENTRYPOINT도 같은 서버를 실행하므로 check_mcp는 이미지 자체를 실행한다.

실제 검증은 initialize/tools/list/resources/read와 도구5개×전체/필터/빈결과/잘못된인자=20호출이다. network=none·read-only root·비root·cap-drop=ALL로 확인했다. 데이터 읽기 권한만 제공한다. Windows 로컬 subprocess는 이번 환경에서 응답 대기가 있어 Docker 경로를 실행 검증 기준으로 사용했다.

verify_practice는 명세·파일의 로컬 정합성만 검사하며 실제 컨테이너를 띄우지 않는다. 그 결과 actual_mcp_verified=false는 이 정적 검사 자체가 실통신을 확인하지 않는다는 뜻이다. 실제 MCP 통신 증거는 verification.json/check_mcp 보고서다.

## MCP 응답과 시작 검사

도구 결과는 MCP TextContent 안 JSON 배열이다. structuredContent는 사용하지 않는다. 인자 오류는 isError=true다. 메타데이터는 도구를 추가하지 않고 resources/read의 slotagent://practice/manifest에서 제공한다. version/data_version/snapshot_hashes/도구·input_schema·decoded_output_schema를 반환한다.

①은 새 trial/attempt마다 새 컨테이너를 띄우고 종료 후 제거해야 한다. 데이터 버전/해시·도구 목록·스키마·접속을 검사해 sa_env_checks에 기록하고 불일치하면 실행하지 않는다. 그 제품 수명주기 구현과 기록 저장은 아직 통합 검증하지 않았다.

후보 서버↔연습 서버 매핑에서 후보 도구의 차이를 같은 구현으로 지우지 않도록 ①②가 확인해야 한다. 공식 실행 명세 저장 위치·metadata 규약·어댑터 버전 기록도 [① 전달 문서](../../../../docs/role2_handoff_20261124.md)의 확인 요청이다. P-05 정책/DB 결정은 별도 문서를 따른다.

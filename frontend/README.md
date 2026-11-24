# SlotAgent UI

공유용 데모 HTML을 Next.js App Router + TypeScript로 옮긴 프런트엔드입니다. Tailwind CSS와 shadcn/ui 방식의 공통 Button을 사용하며, 제공된 SVG·색상·레이아웃을 재사용합니다.

## 실행

Node.js 20.9 이상이 필요합니다. 저장소 루트가 아니라 `frontend/`에서 실행합니다.

```powershell
cd frontend
npm ci
npm run dev
```

브라우저에서 http://127.0.0.1:3000 을 엽니다.

```powershell
npm run generate:types
npm run typecheck
npm run build
npm run start
```

## 구현 범위

- 홈과 데모 일러스트, 데스크톱 사이드 메뉴·모바일 하단 메뉴
- 에이전트 등록: API 정보 입력, JSON 업로드, Runner 정보 입력, 예시 사용
- 에이전트 선택 → GitHub 교체 후보 → 시험 기준 → 모의 진행·중단 → 결과 → 한 장 요약
- 후보별 비용·정확도·속도, 쉽게/자세히 보기, 판정 설명
- 비교 기록 및 등록 정보의 브라우저 저장, 밝은/어두운 테마
- 예시 답변으로 이용 방법을 알려주는 SlotBot
- 브라우저 인쇄를 통한 요약 PDF 저장

### 기획 1.3에 맞춘 화면 보완

- 등록: 기본 지시, 모델 종류·버전, 답변 다양성(온도), 도구별 읽기·쓰기 확인, 쓰기 시험 방식과 확인란
- 시험 계획: 문제 수·반복·예산, 기존 예시 단가 기반 예상 비용, 예산 초과 차단·문제 수 축소, 시작 전 확인
- 상세 결과: 예시의 유형별 성공 횟수·첫 실패·p90·반복 성공·기능 범위, 설명용 실행 순서 패널
- 요약: 예시 성공률 차이·범위·문항/유형 수·측정 조건과 저장한 시험 계획
- API: 진단 전용 안내, 교체 비교 진입 차단 (실제 진단 연동은 미구현)

사용자가 바꾸는 시험 계획과 재생하는 기존 결과는 구분합니다. 계획을 바꿔도 11개 유형·46문항·2회 반복의 원래 예시 기록을 새 측정값으로 바꾸지 않습니다. 도구별 시간·비용, 완주율, 정확한 모델·데이터 버전, 최소 판별 차이·예상 실행 시간처럼 근거가 없는 값은 측정 전 또는 연결 전으로 표시합니다. 등록한 사용자 에이전트를 실제로 평가했다고 표시하지 않습니다.

실제 API 연결, Runner 실행, LLM 호출, 도구 실행, 결제, 인증, 공유 링크 발급은 연결하지 않았습니다. 비교는 고정된 예시 기록을 재생합니다. 기대 변화는 기록에 저장되며 예시 채점 데이터를 바꾸지 않습니다. 비용·속도 우선과 성능 우선에 따른 판정 차이는 화면에 반영합니다. 실제 에이전트 설정을 수정하지 않습니다.

기록은 `localStorage`의 `slotagent-ui-v1` 키로 최근 50건을 보관합니다. 기존 비교는 당시의 사용량·후보·에이전트 스냅샷으로 표시합니다. 홈의 결과 미리보기는 비교 기록에 넣지 않습니다. 저장 공간을 사용할 수 없으면 안내합니다.

## 폴더

```text
src/app/                 # Next.js 페이지 진입점·레이아웃
src/features/slotagent/
  components/            # SlotAgent 화면 흐름, 등록, SlotBot
  mocks/                 # 화면 전용 예시 데이터·타입 (API 계약과 구분)
  storage.ts             # SlotAgent 브라우저 저장
src/components/ui/       # 공통 UI (shadcn/ui 방식 Button)
src/styles/              # 데모 스타일·전역 스타일·반응형 보정
src/lib/                 # 공통 클래스 유틸리티
src/types/contracts.ts   # 스키마에서 생성한 API 타입, 직접 수정 금지
public/demo/             # 공유용 HTML에서 추출한 원본 SVG
scripts/                 # API 계약 타입 생성
config/                  # 별도 경로를 지원하는 도구 설정 (Playwright)
tests/                   # 데스크톱·모바일 브라우저 시나리오
```

최상단의 package.json·package-lock.json은 npm 패키지 관리, next.config.ts·postcss.config.mjs는 프레임워크 설정, components.json은 shadcn CLI, tsconfig.json은 편집기와 TypeScript의 기본 탐색 위치에 맞춰 유지합니다. next-env.d.ts는 Next.js가 생성하는 타입 선언입니다. TypeScript 증분 캐시는 `.next/cache/`에 생성합니다.

화면 상태는 React로 관리합니다. 실제 API를 연결할 때는 설치된 TanStack Query로 조회·폴링을 추가하고, 입출력 타입은 `src/types/contracts.ts`를 사용합니다. 타입 원본은 `../contracts/schemas/api.schema.json`과 참조 스키마이며, 생성기는 참조를 함께 해석합니다. 계약 스키마를 변경하지 않았습니다.

## JSON 등록 예시

데모 HTML의 설정 파일 형식을 읽는 **화면 체험용 가져오기 형식**입니다. 백엔드의 `register_agent_request`와 다릅니다.

```json
{
  "name": "우리 팀 GitHub 도우미",
  "job": "배포 상태와 이슈, PR을 찾아요.",
  "prompt": "도구로 확인한 사실만 답해 주세요.",
  "provider": "GPT",
  "model": "GPT 계열",
  "temperature": 0,
  "tools": [{ "s": "github", "how": "mcp", "access": "read" }]
}
```

1MB 이하 JSON 객체를 읽습니다. 등록되지 않은 서비스나 잘못된 데이터 형식은 거절합니다. `tools`가 없으면 도구 탐색 대기로 표시하고, GitHub 도구가 확인되지 않은 에이전트는 GitHub 비교를 시작할 수 없습니다. API 방식은 주소 형식을 확인하고 이름·업무 등 기본 등록 정보를 저장하며, 실제 도구 탐색은 수행하지 않습니다.

## 브라우저 검증

최초 한 번 Playwright Chromium을 설치합니다.

```powershell
npx playwright install chromium
npm run test:e2e
```

데스크톱과 모바일에서 후보 선택 제한, 중단·재시작, 완료·요약, 기록 복원, 파일 검증, 테마, SlotBot을 확인합니다. 스크린샷은 Git에서 제외되는 `test-results/`에 저장됩니다.

/* Generated from contracts/schemas/api.schema.json. Run npm run generate:types; do not edit. */

/**
 * 쓰는 역할 ④ · 읽는 역할 ①. 자리 하나에서 '무엇으로 바꾸는지'만 적음. 나머지는 agent_spec 그대로. kind 는 candidates.component_kind 와 같아야 함. spec_hash = canonical_hash(component_spec)
 */
export type CandidatesComponentSpec = {
  schema_version: 1;
  kind: "tool_bundle" | "custom_tool" | "tool_search" | "prompt" | "model" | "skill" | "workflow";
  [k: string]: unknown;
} & (ToolBundle | CustomTool | ToolSearch | Prompt | Model);
/**
 * 만드는 쪽 공동(reports/) · 읽는 쪽 화면·④ chatbot. 숫자는 모두 comparisons·trials 에서 옴 → evidence 에 근거 행 번호. chatbot 은 이 숫자만 말함 (FR-BOT-02)
 */
export type ReportsContent = {
  [k: string]: unknown;
} & {
  schema_version: 1;
  kind: "one_pager" | "detail";
  /**
   * 신호등. 금지 행동 1번이면 red (관문)
   */
  light: "green" | "yellow" | "red";
  verdict: "adopt" | "conditional" | "hold" | "reject";
  /**
   * 한 줄 이유 (쉬운 말)
   */
  headline: string;
  candidates?: {
    /**
     * 후보 표시 A, B, C (변형은 C-noH 등)
     */
    label: string;
    name: string;
    role: "baseline" | "candidate" | "variant";
    /**
     * 10번 중 몇 번 같은 말로 쓸 원본
     */
    success?: {
      k?: number;
      n?: number;
    };
    /**
     * 원 단위 금액 (0 이상)
     */
    monthly_cost_krw?: number;
    latency_p50_sec?: number;
  }[];
  /**
   * 근거 행 번호. 비교 수치는 comparison_id, 금지 행동처럼 풀이 하나가 근거면 trial_id
   *
   * @minItems 1
   */
  evidence: [
    (
      | {
          [k: string]: unknown;
        }
      | {
          [k: string]: unknown;
        }
    ),
    ...(
      | {
          [k: string]: unknown;
        }
      | {
          [k: string]: unknown;
        }
    )[]
  ];
  risks?: string[];
  /**
   * 전제 조건 (같은 조건 상대 비교, 평가팩 버전 등)
   */
  premises?: string[];
  caveats: {
    /**
     * 잠근 뒤 기준을 바꿨으면 true (탐색적 결과)
     */
    exploratory: boolean;
    /**
     * 도메인 검증(E1~E6) 전이면 false → '채점 검증 전' 표시
     */
    grader_validated: boolean;
    /**
     * 한 자리만 바꾸면 true. 여러 곳이 바뀌면 false → '원인 특정 불가' 표시
     */
    cause_identifiable?: boolean;
  };
  /**
   * kind=detail 일 때만 (개발자용 자세히 보기)
   */
  detail?: {
    /**
     * 문항 유형별 결과
     */
    by_template: {
      template_code: string;
      /**
       * 후보 표시 A, B, C (변형은 C-noH 등)
       */
      label: string;
      k: number;
      n: number;
      out_of_scope?: number;
    }[];
    /**
     * 후보 label → 첫 실패 유형(trial_grades.first_fail_type) → 건수
     */
    fail_types: {
      [k: string]: {
        [k: string]: number;
      };
    };
    /**
     * 도구 시간 상위 10개 (trial_metrics.tool_sec_by_tool 합). 나머지는 화면에서 펼쳐 보기
     *
     * @maxItems 10
     */
    tool_time_top:
      | []
      | [
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          }
        ]
      | [
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          }
        ]
      | [
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          }
        ]
      | [
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          }
        ]
      | [
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          }
        ]
      | [
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          }
        ]
      | [
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          }
        ]
      | [
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          }
        ]
      | [
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          }
        ]
      | [
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          },
          {
            tool: string;
            /**
             * 후보 표시 A, B, C (변형은 C-noH 등)
             */
            label: string;
            calls: number;
            median_sec: number;
            total_sec?: number;
          }
        ];
  };
};

/**
 * 화면·chatbot ↔ 백엔드. 등록·초안 쪽 API는 ④, 평가팩 목록은 ②, 실행·상태는 ①, 결과·리포트는 ③·공동. 오류는 모두 error 모양
 */
export interface ApiContracts {
  error?: Error;
  register_agent_request?: RegisterAgentRequest;
  register_agent_response?: RegisterAgentResponse;
  register_candidate_request?: RegisterCandidateRequest;
  pack_list_response?: PackListResponse;
  plan_proposal_request?: PlanProposalRequest;
  plan_proposal_response?: PlanProposalResponse;
  create_experiment_request?: CreateExperimentRequest;
  create_experiment_response?: CreateExperimentResponse;
  run_response?: RunResponse;
  stop_request?: StopRequest;
  status_response?: StatusResponse;
  results_response?: ResultsResponse;
  report_response?: ReportResponse;
}
/**
 * DB 거절도 이 모양으로 바꿔 돌려줌. code 는 DB 가 붙인 HINT(0003) 또는 제약 이름으로 고름 — 문구로 고르지 않음 (api/eng_errors.py). message 는 사용자에게 그대로 보여도 되는 문구
 */
export interface Error {
  code:
    | "invalid_spec"
    | "invalid_plan"
    | "limit_exceeded"
    | "baseline_exists"
    | "label_taken"
    | "wrong_slot"
    | "immutable"
    | "experiment_locked"
    | "not_lockable"
    | "not_found"
    | "budget_exceeded"
    | "proposal_stale"
    | "internal";
  message: string;
  /**
   * 스키마 오류 위치, DB 원문 등 (개발자용)
   */
  detail?:
    | {
        [k: string]: unknown;
      }
    | string
    | null;
}
/**
 * ④ POST /api/agents — 에이전트와 첫 버전 등록. 백엔드가 spec.tools 의 (service, access) 마다 자리(slots)를 만들고, 자리마다 기준 후보 A(지금 구성)를 agent_spec 에서 자동으로 만듦 (common.checks.baseline_component)
 */
export interface RegisterAgentRequest {
  name: string;
  purpose?: string;
  /**
   * 등록 질문 1번의 도메인 (sa_domains 드롭다운, 11/23). 모르면 비움
   */
  domain_code?: string;
  /**
   * 한 달 예상 호출 수 → 리포트 monthly_cost_krw. 모르면 비움
   */
  expected_monthly_calls?: number;
  version: {
    connection_type: "spec_upload" | "runner" | "api";
    control_level: "C0" | "C1" | "C2";
    model: string;
    temperature: number;
    instructions: string;
    spec: AgentVersionsSpec;
  };
}
/**
 * 쓰는 역할 ④ · 읽는 역할 ①(build_config_snapshot). 모델·온도·지시문은 agent_versions 의 칸에 따로 있음. spec_hash = canonical_hash({model, temperature, instructions, spec})
 */
export interface AgentVersionsSpec {
  schema_version: 1;
  /**
   * 에이전트가 쓰는 서비스. 자리(slots)는 (service, access) 마다 하나로 나옴
   *
   * @minItems 1
   */
  services: [
    {
      /**
       * github, slack, postgres ...
       */
      code: string;
      name: string;
    },
    ...{
      /**
       * github, slack, postgres ...
       */
      code: string;
      name: string;
    }[]
  ];
  /**
   * @maxItems 5
   */
  mcp_servers?:
    | []
    | [McpServer]
    | [McpServer, McpServer]
    | [McpServer, McpServer, McpServer]
    | [McpServer, McpServer, McpServer, McpServer]
    | [McpServer, McpServer, McpServer, McpServer, McpServer];
  /**
   * 지금 켜져 있는 도구 전부 (MCP 가 꺼내 준 것 포함). 등록 한도 50개
   *
   * @minItems 1
   * @maxItems 50
   */
  tools: [ToolDef, ...ToolDef[]];
  /**
   * [확장] Skill 이름과 내용 해시. 8주 안에는 비워 둠
   *
   * @maxItems 10
   */
  skills?:
    | []
    | [
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        }
      ]
    | [
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        }
      ]
    | [
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        }
      ]
    | [
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        }
      ]
    | [
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        }
      ]
    | [
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        }
      ]
    | [
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        }
      ]
    | [
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        }
      ]
    | [
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        }
      ]
    | [
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        },
        {
          name: string;
          /**
           * common.hashing.canonical_hash() 결과
           */
          content_hash: string;
        }
      ];
  runtime?: Runtime;
}
export interface McpServer {
  name: string;
  /**
   * github-mcp-server 등 배포 이름
   */
  package?: string;
  /**
   * 서버 버전. 바뀌면 다른 구성(재현성)
   */
  version: string;
  transport?: "stdio" | "http";
  /**
   * 컨테이너로 띄우면 이미지 digest
   */
  image_digest?: string | null;
}
/**
 * 모델에게 보이는 도구 하나. 함수 호출 형식(이름·설명·인자 JSON Schema)
 */
export interface ToolDef {
  name: string;
  description: string;
  /**
   * 인자 JSON Schema (그대로 모델에 전달)
   */
  parameters: {
    [k: string]: unknown;
  };
  /**
   * github, slack, postgres ...
   */
  service: string;
  access: "read" | "write";
  /**
   * mcp:<서버 이름> | custom | builtin
   */
  origin: string;
  /**
   * 직접 만든 도구(custom)만. 8주 안에는 정해 둔 가짜 응답으로 실행. 인자가 맞는 첫 항목을 돌려줌
   */
  fixed_responses?: {
    /**
     * 인자 일부가 같으면 맞음. {} 는 항상 맞음
     */
    when: {
      [k: string]: unknown;
    };
    /**
     * 모델이 받는 결과 문자열
     */
    result: string;
  }[];
}
export interface Runtime {
  /**
   * LLM 호출 + 도구 호출 상한
   */
  max_steps: number;
  /**
   * 풀이 하나 제한 시간 (ERD 확정: 5분)
   */
  timeout_sec: number;
  /**
   * LLM API 일시 오류 재시도 (trials.api_retries 로 기록)
   */
  max_api_retries?: number;
  /**
   * LLM 호출 한 번의 출력 토큰 상한. 비우면 모델 기본값
   */
  max_output_tokens?: number;
}
export interface RegisterAgentResponse {
  /**
   * DB 내부 번호 (bigint)
   */
  agent_id: number;
  /**
   * DB 내부 번호 (bigint)
   */
  agent_version_id: number;
  slots: {
    /**
     * DB 내부 번호 (bigint)
     */
    slot_id: number;
    name: string;
    /**
     * github, slack, postgres ...
     */
    service: string;
    access: "read" | "write";
    comparable: boolean;
    not_comparable_reason?: string | null;
    /**
     * DB 내부 번호 (bigint)
     */
    baseline_candidate_id: number;
  }[];
}
/**
 * ④ POST /api/slots/{slot_id}/candidates. 기준 후보는 등록 때 자동으로 생기므로 여기서는 기준이 아닌 후보만
 */
export interface RegisterCandidateRequest {
  /**
   * 후보 표시 A, B, C (변형은 C-noH 등)
   */
  label: string;
  name: string;
  component_spec: CandidatesComponentSpec;
}
/**
 * 자리의 도구 묶음을 바꿈. 자리 (service, access) 의 기존 도구는 모두 빼고 이 목록으로 채움
 */
export interface ToolBundle {
  schema_version: 1;
  kind: "tool_bundle";
  /**
   * github, slack, postgres ...
   */
  service: string;
  access: "read" | "write";
  mcp_server?: McpServer1;
  /**
   * 켜는 도구 전부. 모두 이 묶음의 service·access 와 같아야 함 (검사: common.checks.check_component). 무료 평가는 20개까지 — 한도 검사는 ④ 저장 함수
   *
   * @minItems 1
   * @maxItems 50
   */
  tools: [ToolDef, ...ToolDef[]];
}
/**
 * 이 묶음을 꺼내 주는 서버 (없으면 직접 정의). 자리 밖 도구가 쓰는 서버와 이름이 같은데 내용이 다르면 build_config_snapshot 이 거절함 — 다른 자리까지 바뀌어 '한 자리만 바꿈'이 깨지므로. 새 서버는 다른 이름으로
 */
export interface McpServer1 {
  name: string;
  /**
   * github-mcp-server 등 배포 이름
   */
  package?: string;
  /**
   * 서버 버전. 바뀌면 다른 구성(재현성)
   */
  version: string;
  transport?: "stdio" | "http";
  /**
   * 컨테이너로 띄우면 이미지 digest
   */
  image_digest?: string | null;
}
/**
 * 자리의 도구를 직접 만든 도구(1~10개)로 바꿈. 도구마다 정해 둔 가짜 응답(fixed_responses) 필수
 */
export interface CustomTool {
  schema_version: 1;
  kind: "custom_tool";
  /**
   * github, slack, postgres ...
   */
  service: string;
  access: "read" | "write";
  /**
   * @minItems 1
   * @maxItems 10
   */
  tools:
    | [
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        }
      ]
    | [
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        }
      ]
    | [
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        }
      ]
    | [
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        }
      ]
    | [
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        }
      ]
    | [
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        }
      ]
    | [
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        }
      ]
    | [
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        }
      ]
    | [
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        }
      ]
    | [
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        },
        ToolDef & {
          origin?: "custom";
          [k: string]: unknown;
        }
      ];
}
/**
 * 고도화 D (11/23). 자리의 도구를 tools 로 바꾸되, 도구 설명을 처음에 다 보여 주지 않고 검색 도구로 필요할 때 찾아 불러옴. 합치는 규칙은 tool_bundle 과 같고(자리 도구를 모두 빼고 tools 로 채움), 스냅숏에 tool_search 칸이 더 붙음
 */
export interface ToolSearch {
  schema_version: 1;
  kind: "tool_search";
  /**
   * github, slack, postgres ...
   */
  service: string;
  access: "read" | "write";
  mcp_server?: McpServer2;
  /**
   * 검색 대상 도구 전부. 모두 이 후보의 service·access 와 같아야 함 (common.checks.check_component)
   *
   * @minItems 1
   * @maxItems 50
   */
  tools: [ToolDef, ...ToolDef[]];
  search: {
    /**
     * 검색 방법. 8주 안에는 BM25(rank-bm25)만
     */
    method: "bm25";
    /**
     * 검색 한 번에 불러오는 도구 수
     */
    top_k: number;
    /**
     * 검색 없이 처음부터 보여 줄 도구 이름. tools 안에 있어야 함
     *
     * @maxItems 10
     */
    always_loaded?:
      | []
      | [string]
      | [string, string]
      | [string, string, string]
      | [string, string, string, string]
      | [string, string, string, string, string]
      | [string, string, string, string, string, string]
      | [string, string, string, string, string, string, string]
      | [string, string, string, string, string, string, string, string]
      | [string, string, string, string, string, string, string, string, string]
      | [string, string, string, string, string, string, string, string, string, string];
  };
}
/**
 * tool_bundle 과 같음
 */
export interface McpServer2 {
  name: string;
  /**
   * github-mcp-server 등 배포 이름
   */
  package?: string;
  /**
   * 서버 버전. 바뀌면 다른 구성(재현성)
   */
  version: string;
  transport?: "stdio" | "http";
  /**
   * 컨테이너로 띄우면 이미지 digest
   */
  image_digest?: string | null;
}
/**
 * [확장] 지시문만 바꿈
 */
export interface Prompt {
  schema_version: 1;
  kind: "prompt";
  instructions: string;
}
/**
 * [확장] 모델만 바꿈
 */
export interface Model {
  schema_version: 1;
  kind: "model";
  model: string;
  temperature?: number;
}
/**
 * ② GET /api/packs?domain=it_ops — 잠긴 평가팩 버전 목록 (실험에 쓸 수 있는 것만)
 */
export interface PackListResponse {
  packs: {
    /**
     * DB 내부 번호 (bigint)
     */
    pack_version_id: number;
    pack_code: string;
    version: string;
    domain_code: string;
    n_templates: number;
    n_tasks: number;
    n_held_templates?: number;
    locked_at: string;
  }[];
}
/**
 * ① 1차(응답 모양 책임), 값은 ②③ — POST /api/experiments/plan-proposal — ④가 prereg·plan 값을 직접 만들지 않도록 받는 곳. 백엔드가 settings 기본값(③②) + stats.sample_size(③) + packs.select_tasks(②) 로 만듦. 저장하지 않음
 */
export interface PlanProposalRequest {
  /**
   * DB 내부 번호 (bigint)
   */
  agent_version_id: number;
  /**
   * DB 내부 번호 (bigint)
   */
  slot_id: number;
  /**
   * DB 내부 번호 (bigint)
   */
  pack_version_id: number;
  /**
   * @minItems 1
   * @maxItems 3
   */
  candidate_ids: [number] | [number, number] | [number, number, number];
  /**
   * 고르는 문항 쪽. 기본 held (확인용). dev 는 고칠 때만
   */
  split?: "held" | "dev";
  reps?: number;
  /**
   * 원 단위 금액 (0 초과). 예산처럼 DB 가 > 0 을 요구하는 칸
   */
  budget_krw?: number;
}
/**
 * plan 에는 proposal 칸이 없음. ④는 create 요청에 proposal = {request(보낸 요청), as_of(이 값)} 를 넣음
 */
export interface PlanProposalResponse {
  prereg: ExperimentsPrereg;
  /**
   * 요청·응답에 오가는 모양 = proposal 칸 없음 (서버만 채움)
   */
  plan: ExperimentsPlan;
  reps: number;
  n_templates: number;
  n_tasks: number;
  /**
   * 후보 × 문항 × 반복 (계산값, 저장 안 함)
   */
  trials: number;
  warnings?: string[];
  /**
   * 제안을 만든 시각 (서버 시각). 다시 계산할 때 이 시각의 settings·task_exposures 를 씀
   */
  as_of: string;
}
/**
 * 내용을 정하는 역할 ③ · 저장하는 역할 ④(초안) · 읽는 역할 ①(오류 처리)·③(판정). ④는 값을 직접 정하지 않고 POST /api/experiments/plan-proposal 이 돌려준 prereg 를 그대로 저장함 (기본값은 settings, 계산은 ③). 잠근 뒤 바꾸면 exploratory=true. outcome_rules·max_env_retries 가 없으면 DB가 잠금을 막음
 */
export interface ExperimentsPrereg {
  schema_version: 1;
  primary_metric: "success_rate";
  /**
   * ni_then_sup = 비열등성 먼저, 통과하면 우월성까지 (판정 4종의 기본). 하나만 볼 때 noninferiority / superiority
   */
  test: "ni_then_sup" | "noninferiority" | "superiority";
  /**
   * 비열등성 마진 %p (기본값 settings ni_margin_pp, 기획서 1.2: 5)
   */
  margin_pp: number;
  /**
   * 유의수준. analyses.method.correction.alpha 는 이 값의 기록용 복사본 (저장할 때 같은지 확인: common.checks.check_method)
   */
  alpha: number;
  /**
   * success_rate 는 1차 지표라 넣지 않음. 회귀율은 지표가 아니라 regression_limit 로 보고 comparisons.regression_rate 칸에 기록
   */
  secondary_metrics?: ((
    "success_rate" | "cost_per_success_krw" | "latency_p50_sec" | "tool_calls_mean" | "completion_rate"
  ) & {
    [k: string]: unknown;
  })[];
  /**
   * 예상 방향 (사전에 적어 둠)
   */
  expected?: {
    /**
     * 후보 표시 A, B, C (변형은 C-noH 등)
     */
    better_label?: string;
    diff_pp?: number;
  };
  /**
   * 회귀율 한도 (기본값 settings regression_limit, 기획서 1.2: 0.05)
   */
  regression_limit?: number;
  sequential?: {
    method: "none" | "group_sequential";
    /**
     * 중간 분석 횟수 (마지막 포함). plan.tasks 의 가장 큰 batch_no 와 같아야 함 (common.checks.check_plan)
     */
    looks?: number;
  };
  /**
   * 풀이·채점 결과를 성공률에 어떻게 셀지. ①이 실행 결과를 남기고 ③이 이 규칙대로 셈
   */
  outcome_rules: {
    /**
     * 후보 탓 오류
     */
    agent_error: "fail";
    timeout: "fail";
    /**
     * 우리 환경 탓. max_env_retries 까지 다시 실행 후에도 오류면 분석 단위에서 뺌
     */
    env_error: "retry_then_exclude";
    grader_error: "exclude";
    undecidable: "exclude";
    /**
     * ⚠ 팀 확정 전 (기획서 1.2 '세지 않음' = exclude / 수정 요청서 '셈' = fail)
     */
    out_of_scope: "fail" | "exclude";
    /**
     * env_error 로 볼 outcome_reason 목록 (필수 — 비면 ①이 환경 탓과 후보 탓을 가를 수 없음). 기본값 settings env_error_reasons. env_ 로 시작하는 값 + 팀이 정하면 llm_api_429
     *
     * @minItems 1
     */
    env_error_reasons: [
      (
        | "env_mcp_server_down"
        | "env_practice_repo_unreachable"
        | "env_practice_db_unreachable"
        | "env_llm_api_5xx"
        | "env_worker_lost"
        | "env_write_proxy_error"
        | "llm_api_429"
        | "agent_max_steps"
        | "agent_invalid_tool_call"
        | "agent_llm_refused"
        | "agent_crash"
        | "timeout_wall_clock"
      ) &
        (
          | {
              [k: string]: unknown;
            }
          | "llm_api_429"
        ),
      ...((
        | "env_mcp_server_down"
        | "env_practice_repo_unreachable"
        | "env_practice_db_unreachable"
        | "env_llm_api_5xx"
        | "env_worker_lost"
        | "env_write_proxy_error"
        | "llm_api_429"
        | "agent_max_steps"
        | "agent_invalid_tool_call"
        | "agent_llm_refused"
        | "agent_crash"
        | "timeout_wall_clock"
      ) &
        (
          | {
              [k: string]: unknown;
            }
          | "llm_api_429"
        ))[]
    ];
  };
  max_env_retries: number;
}
/**
 * 문항 고르기 ②(평가팩) · 문항 수·묶음 ③ · 저장 ④ · 읽기 ①(lock_experiment 가 tasks 로 풀이 행을 만듦). ④는 POST /api/experiments/plan-proposal 이 돌려준 plan 을 보냄 (proposal 칸 없이). proposal 칸은 저장할 때 서버(common.proposal)가 채움 — 저장된 행은 part='stored' 로 검사. 잠근 뒤 바꿀 수 없음. 저장 전 검사: common.checks.check_plan
 */
export interface ExperimentsPlan {
  schema_version: 1;
  /**
   * 풀 문항과 순차 검정 묶음. 순서 = 실행 순서. task_id 겹침 금지, 같은 문항 유형(template)은 한 묶음에만, 묶음 번호는 1부터 빈틈 없이 (check_plan)
   *
   * @minItems 1
   */
  tasks: [
    {
      /**
       * DB 내부 번호 (bigint)
       */
      task_id: number;
      batch_no: number;
    },
    ...{
      /**
       * DB 내부 번호 (bigint)
       */
      task_id: number;
      batch_no: number;
    }[]
  ];
  min_detectable_pp?: number;
  /**
   * 잠그기 전에 보여 주는 예상 (FR-EXP-03). 문항 수·풀이 수는 tasks 로 계산되니 두지 않음 (화면이 계산하거나 plan-proposal 응답에서 받음)
   */
  estimate?: {
    /**
     * 원 단위 금액 (0 이상)
     */
    cost_krw?: number;
    minutes?: number;
  };
  /**
   * 사전 등록 추적 (3차 5). 모두 서버가 씀 — ④가 보낸 {request, as_of} 로 서버가 plan-proposal 을 다시 계산해 저장할 값과 비교. hash = canonical_hash({prereg, plan}) (다시 계산한 제안의 해시, plan 의 proposal 칸 뺌)
   */
  proposal?: {
    request: PlanProposalRequest1;
    /**
     * 제안을 만든 시각 (plan_proposal_response.as_of). 다시 계산할 때 이 시각의 settings 를 씀
     */
    as_of: string;
    /**
     * common.hashing.canonical_hash() 결과
     */
    hash: string;
    /**
     * 저장한 값이 제안과 다르면 true (서버가 비교)
     */
    edited: boolean;
    /**
     * 제안과 다른 칸 (서버가 비교). prereg·plan 은 맨 위 칸 단위, 실험 칸은 reps·budget_krw·candidates
     */
    edited_fields: string[];
  };
}
/**
 * ④가 plan-proposal 에 보낸 요청 그대로
 */
export interface PlanProposalRequest1 {
  /**
   * DB 내부 번호 (bigint)
   */
  agent_version_id: number;
  /**
   * DB 내부 번호 (bigint)
   */
  slot_id: number;
  /**
   * DB 내부 번호 (bigint)
   */
  pack_version_id: number;
  /**
   * @minItems 1
   * @maxItems 3
   */
  candidate_ids: [number] | [number, number] | [number, number, number];
  /**
   * 고르는 문항 쪽. 기본 held (확인용). dev 는 고칠 때만
   */
  split?: "held" | "dev";
  reps?: number;
  /**
   * 원 단위 금액 (0 초과). 예산처럼 DB 가 > 0 을 요구하는 칸
   */
  budget_krw?: number;
}
/**
 * ④ POST /api/experiments (draft 로 만듦). prereg·plan 은 plan-proposal 응답 값(고쳤으면 고친 값), proposal 은 그 제안의 출처. 후보의 역할은 candidates.is_baseline 에서(기준 = baseline, 나머지 = candidate), label 은 candidates.label 에서 백엔드가 채움 — 요청에서 받지 않음
 */
export interface CreateExperimentRequest {
  kind?: "compare" | "diagnose";
  /**
   * DB 내부 번호 (bigint)
   */
  agent_version_id: number;
  /**
   * DB 내부 번호 (bigint)
   */
  slot_id: number;
  /**
   * DB 내부 번호 (bigint)
   */
  pack_version_id: number;
  reps: number;
  /**
   * 원 단위 금액 (0 초과). 예산처럼 DB 가 > 0 을 요구하는 칸
   */
  budget_krw?: number;
  prereg: ExperimentsPrereg;
  /**
   * 요청·응답에 오가는 모양 = proposal 칸 없음 (서버만 채움)
   */
  plan: ExperimentsPlan;
  /**
   * 기준 후보 1개를 반드시 포함
   *
   * @minItems 1
   * @maxItems 3
   */
  candidates: [number] | [number, number] | [number, number, number];
  /**
   * 어떤 제안에서 왔는지. 서버가 이걸로 제안을 다시 만들어 비교하고 plan.proposal(hash·edited·edited_fields)을 채움 — ④는 고쳤는지 적지 않음
   */
  proposal: {
    request: PlanProposalRequest;
    as_of: string;
  };
}
export interface CreateExperimentResponse {
  /**
   * DB 내부 번호 (bigint)
   */
  experiment_id: number;
  status: "draft";
}
/**
 * ① POST /api/experiments/{id}/run — 잠금(lock_experiment) + run_trial 작업 넣기. 같은 요청을 두 번 보내도 한 번만 잠김
 */
export interface RunResponse {
  /**
   * DB 내부 번호 (bigint)
   */
  experiment_id: number;
  status: "locked" | "running";
  trials_total: number;
}
/**
 * ① POST /api/experiments/{id}/stop — 사용자가 멈춤 (stop_reason = user). 본문 없음. 응답은 status_response
 */
export interface StopRequest {}
/**
 * ① GET /api/experiments/{id}/status. trials 는 계획 단위(후보, 문항, 반복)마다 마지막 실행(run_no 가 가장 큰 행)의 상태로 셈 → 합계 = trials_total. 환경 오류로 다시 돌린 횟수는 env_reruns 에 따로
 */
export interface StatusResponse {
  /**
   * DB 내부 번호 (bigint)
   */
  experiment_id: number;
  status: "draft" | "locked" | "running" | "stopped" | "done" | "failed";
  stop_reason?: ("budget" | "interim" | "user" | "job_failed") | null;
  trials_total: number;
  trials: {
    pending: number;
    running: number;
    finished: number;
    error: number;
    cancelled: number;
  };
  env_reruns?: number;
  /**
   * 원 단위 금액 (0 이상)
   */
  cost_krw: number;
  budget_krw?: number | null;
  latest_grading_run_id?: number | null;
  latest_analysis_id?: number | null;
}
/**
 * ③·공동 GET /api/experiments/{id}/results — 가장 최근 분석의 비교 결과
 */
export interface ResultsResponse {
  /**
   * DB 내부 번호 (bigint)
   */
  experiment_id: number;
  /**
   * DB 내부 번호 (bigint)
   */
  analysis_id: number;
  is_interim: boolean;
  comparisons: {
    /**
     * DB 내부 번호 (bigint)
     */
    comparison_id: number;
    /**
     * 후보 표시 A, B, C (변형은 C-noH 등)
     */
    label: string;
    /**
     * 후보 표시 A, B, C (변형은 C-noH 등)
     */
    baseline_label: string;
    /**
     * 지표 이름 한 목록. prereg.secondary_metrics · comparisons.metric(DB CHECK, 0003) 이 같은 목록을 씀. 회귀율은 지표가 아니라 comparisons.regression_rate 칸 하나에만 둠 (3차 8)
     */
    metric: "success_rate" | "cost_per_success_krw" | "latency_p50_sec" | "tool_calls_mean" | "completion_rate";
    diff: number;
    ci_low: number;
    ci_high: number;
    ci_level: number;
    verdict?: "adopt" | "conditional" | "hold" | "reject" | null;
    reason?: string | null;
  }[];
  reports: {
    /**
     * DB 내부 번호 (bigint)
     */
    report_id: number;
    kind: "one_pager" | "detail";
  }[];
}
/**
 * 공동 GET /api/reports/{id} (보기 전용 링크는 GET /api/shared/{token})
 */
export interface ReportResponse {
  /**
   * DB 내부 번호 (bigint)
   */
  report_id: number;
  /**
   * DB 내부 번호 (bigint)
   */
  experiment_id: number;
  content: ReportsContent;
}

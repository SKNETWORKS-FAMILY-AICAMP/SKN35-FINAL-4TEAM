"""전처리 담당과 학습 담당이 함께 보는 약속. 주로 고칠 파일입니다."""
from pathlib import Path

ROOT = Path(__file__).parent
TRAIN_CSV = ROOT / "data" / "train.csv"   # 학습·교차검증용 (전처리 결과)
FINAL_CSV = ROOT / "data" / "final.csv"   # 최종 평가용 (마지막에만 엽니다)
REPORTS = ROOT / "reports"
MODELS = ROOT / "models"

LABEL = "is_wrong"             # 1 = 오답, 0 = 정답
META = ["run_id", "task_id", "template_id", "candidate", "config"]  # 분할·분석에만 씀. 모델에 넣지 않음

# [채울 곳 1] 모델에 넣을 특징. 전처리 표에 같은 이름의 숫자 칸이 있어야 합니다.
# 정답을 모르는 상태에서, 실행 기록만 보고 계산할 수 있는 값만 넣습니다.
FEATURES = [
    "n_tool_calls",        # 도구 호출 수
    "n_tool_errors",       # 도구 오류 수
    "n_empty_results",     # 빈 결과 수
    "n_repeat_calls",      # 같은 도구·같은 인자 반복 수
    "in_tokens",           # 입력 토큰
    "out_tokens",          # 출력 토큰
    "answer_len",          # 최종 답 글자 수
    "says_none",           # "없습니다" 같은 단정 표현 (0/1)
    "asks_back",           # 되묻는 표현 (0/1)
    "grounded_ratio",      # 답의 값 중 도구 결과에 나온 비율 (0~1, 답에 값이 없으면 빈칸)
]

# 이 이름이 특징에 있으면 학습을 멈춥니다 (정답이 새는 칸).
# 주의: 이름만 검사합니다. 다른 이름으로 바꿔 넣은 정답은 잡지 못합니다.
FORBIDDEN = {LABEL, *META, "correct", "done", "violation", "pid", "tpl", "cand", "cfg",
             "target", "scope_a", "rep", "final", "expected", "answer_key"}

# [채울 곳 2] 학습 설정
SEED = 42
N_SPLITS = 5
TARGET_RECALL = 0.8            # 학습 데이터에서 오답을 이만큼 잡도록 기준점을 정함
LGBM_PARAMS = dict(n_estimators=200, learning_rate=0.05, num_leaves=15,
                   min_child_samples=20, class_weight="balanced")
FINAL_MODEL = "lightgbm"       # 교차검증 결과를 보고 고름: logistic / lightgbm
N_BOOT = 1000

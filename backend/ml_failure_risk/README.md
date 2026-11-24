# 오답 위험 예측 (LightGBM) 뼈대

실행 기록 1건(풀이 1회)을 보고 **이 답이 틀렸을 가능성**을 예측합니다. 채택·기각 판정에는 쓰지 않습니다.
전처리 코드는 여기에 없습니다. 전처리 담당이 아래 모양의 표를 `data/`에 넣으면 됩니다.

## 실행
```bash
cd backend/ml_failure_risk
uv run python make_sample.py      # 연습용 가짜 표 (진짜 표가 없을 때만)
uv run python train.py            # 교차검증 비교, 모델 저장
uv run python evaluate.py --final # 모델을 다 정한 뒤 마지막에 한 번
uv run python -m pytest -q tests  # 안전장치 검사
```
진짜 표로 바꿀 때는 가짜 `data/`, `models/`와 `reports/`의 결과 파일(`final_opened.log` 포함)을 먼저 지웁니다.

## 전처리 표 (`data/train.csv`, `data/final.csv`, UTF-8)
풀이 1회 = 1줄.

| 칸 | 뜻 | 모델 입력 |
|---|---|:---:|
| `run_id` | 줄마다 다른 번호 | X |
| `task_id` | 문항 번호 | X |
| `template_id` | 문항 유형 (없으면 task_id) | X |
| `candidate`, `config` | 후보·설정 이름 | X |
| `is_wrong` | 오답 1, 정답 0 | 라벨 |
| `config.py`의 `FEATURES` 10개 | 숫자. 계산할 수 없으면 빈칸 | O |

- 특징은 **정답을 모르고도** 계산할 수 있어야 합니다.
- `train.csv`와 `final.csv`는 같은 `run_id`·`task_id`·`template_id`가 있으면 안 됩니다.
  번호만 바꾸고 내용이 같은 문항은 자동으로 못 잡으니 사람이 확인합니다.
- 유형이 없는 데이터는 비슷한 문항이 나뉘어 들어갈 수 있으니, 가능하면 사람이 유형을 붙입니다.

## 채울 곳
1. `config.py` **FEATURES** — 특징 추가·제거
2. `config.py` **LGBM_PARAMS, FINAL_MODEL** — 설정과 최종 모델
3. `models.py` — 비교할 모델을 더할 때
4. `reports/*_틀.md` — 결과서

## 안전장치
- 정답·번호·후보·설정 칸이 특징에 있으면 멈춤 (이름으로 검사)
- 교차검증에서 같은 문항 유형이 학습·검증에 함께 있으면 멈춤
- 다수 클래스 모델을 항상 함께 비교
- 최종 평가는 `--final`이 있어야 열리고, 연 횟수를 남김

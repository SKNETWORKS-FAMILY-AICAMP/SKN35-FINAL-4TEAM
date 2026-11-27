# 오답 위험 예측 (LightGBM)

실행 기록 1건(풀이 1회)을 보고 **이 답이 틀렸을 가능성**을 예측합니다. 채택·기각 판정에는 쓰지 않습니다.
`preprocess.py`가 실행 기록 JSONL을 아래 형식의 `data/train.csv`, `data/final.csv`로 변환합니다.

## 현재 상태 — 2026-11-27

- 전처리 완료: 원본 1,656건에서 `cand=A_own`이면서 `scope_a=false`인 108건을 제외했습니다. 학습 1,080건·최종 평가 468건입니다.
- 기준 모델·로지스틱 회귀·LightGBM의 유형 단위 5겹 교차검증을 완료했습니다. PR-AUC(AP)는 각각 0.2093·0.7490·0.9205이며 LightGBM을 선정·저장했습니다.
- 모델·설정·임계값 확정 후 최종 평가를 1회 완료했습니다. PR-AUC(AP) 0.9546, 오답 재현율 94.64%이며 T7 재현율은 40%입니다.
- 자동 오답50·정답50 표본의 사람 검수100건과 결과서 반영을 완료했습니다(11/27, 박민하). 사용자 승인으로 R001·R065를 정답으로 정정하여 최종 정답49·오답51, 자동 라벨과99/100 일치입니다. R064는 자동 채점이 놓친 오답입니다. [검수 집계](reports/human_review_1118/summary.json)와 [정정본](reports/human_review_1118/annotations.corrected.json)을 보존했습니다. 이는 현재 평가팩 판정기·κ·후보별 거짓 성공률 검증과 별개입니다.
- 입력은 11/18 사전 실험의 46문항·11유형·GPT-4.1-mini 1종 기록이며, 현재 50유형 평가팩과 별개입니다. 연습용 데이터·도구 결과 600자 잘림·글자 포함 여부 자동 라벨의 한계가 있습니다.

세부사항: [전처리결과서](reports/전처리결과서.md), [학습결과서](reports/학습결과서.md), [교차검증 비교표](reports/cv_comparison.csv). CSV·모델·수치 결과는 Git 제외 대상이므로 별도 전달이 필요합니다.

## 실행

아래는 새 데이터로 처음 실행하는 순서입니다. 현재 최종 평가는 이미 1회 완료했으므로 결과 확인에는 저장된 보고서를 사용합니다. 학습 재실행은 기존 모델·보고서를 덮어쓸 수 있습니다.

```bash
cd backend/ml_failure_risk
uv run python -m pytest -q tests
uv run python preprocess.py --source <trace_main_20261118_152602.jsonl의_경로>
uv run python train.py            # 교차검증 비교, 모델 저장
uv run python evaluate.py --final # 모델을 다 정한 뒤 마지막에 한 번
```
가짜 표 연습은 진짜 데이터가 없는 별도 작업 사본에서 `make_sample.py` → `train.py`로 수행합니다. 가짜 결과에서 진짜 표로 전환할 때만 가짜 `data/`, `models/`, `reports/` 결과 파일(`final_opened.log` 포함)을 정리하며 `*_틀.md`는 남깁니다. 현재 저장된 실제 실험의 결과·최종 평가 기록은 보존합니다. 전처리는 출력이 이미 있으면 중단하므로 재현 확인에는 별도 `--output-dir`와 `--report`를 지정합니다.

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

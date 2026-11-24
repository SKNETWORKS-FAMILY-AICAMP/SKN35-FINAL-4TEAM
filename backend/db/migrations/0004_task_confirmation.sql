-- 문항별 고정 사용자 답(P-05). 정책 세부 모양은 contracts 검사가 맡고 DB는 JSON 객체인지만 봅니다.
ALTER TABLE sa_tasks ADD COLUMN confirmation jsonb
  CONSTRAINT sa_tasks_confirmation_object CHECK (jsonb_typeof(confirmation) = 'object');
COMMENT ON COLUMN sa_tasks.confirmation IS '문항별 고정 사용자 답 정책(P-05). 엔진 전용이며 모델 입력에 넣지 않음. SQL NULL은 고정 답 없음';

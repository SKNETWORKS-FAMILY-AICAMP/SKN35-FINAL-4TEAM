"""[①] DB 작업 큐. SELECT ... FOR UPDATE SKIP LOCKED, 임대 10분·1분 연장, attempts = 임대 토큰.

    enqueue(conn, payload)          # contracts.validate("job_payload", payload) 후 INSERT
    lease(conn, worker_id) -> job   # attempts += 1
    complete / fail(conn, job_id, attempts)   # attempts 가 같을 때만
"""

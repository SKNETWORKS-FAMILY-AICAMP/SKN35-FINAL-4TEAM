# 전체 테스트 (PostgreSQL 설치 없이 pgserver 가 임시로 띄움)
Set-Location (Join-Path $PSScriptRoot "..\backend")
uv run --no-project -p 3.12 --with jsonschema --with pgserver --with "psycopg[binary]" --with python-dotenv --with openai --with anthropic --with pytest pytest tests   # -q 는 backend/pyproject.toml addopts 에 있음
exit $LASTEXITCODE

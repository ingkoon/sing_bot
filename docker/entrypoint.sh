#!/usr/bin/env bash
set -euo pipefail

# 코드는 `from dico_token import Token` 으로 토큰을 읽는다.
# 이미지에 토큰을 굽지 않기 위해, 컨테이너 시작 시 환경변수에서 생성한다.
if [[ -z "${DISCORD_TOKEN:-}" ]]; then
  echo "[ENTRYPOINT] FATAL: DISCORD_TOKEN 환경변수가 비어 있습니다." >&2
  exit 1
fi

cat > /app/dico_token.py <<EOF
Token = "${DISCORD_TOKEN}"
EOF

echo "[ENTRYPOINT] dico_token.py 생성 완료. 봇을 시작합니다."
exec python ingribo.py

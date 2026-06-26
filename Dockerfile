# syntax=docker/dockerfile:1
FROM python:3.12-slim

# ffmpeg(음원 스트리밍) + libopus0(음성 송출) + curl/unzip(Deno 설치용) 시스템 의존성
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Deno: yt-dlp의 n-challenge(서명 해독) JS 런타임. /usr/local/bin/deno 로 설치되어 PATH에 잡힘.
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

WORKDIR /app

# 의존성 먼저 설치(레이어 캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 봇 소스 (voiceroom/ 하위가 /app 루트로 들어감 → dico_token import 경로 유지)
COPY voiceroom/ ./

# 토큰을 환경변수에서 주입하기 위한 엔트리포인트
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

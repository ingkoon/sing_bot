# CLAUDE.md

이 파일은 이 저장소에서 작업하는 Claude Code(및 기여자)를 위한 가이드입니다.
프로젝트는 **유튜브 기반 디스코드 노래 봇**이며, "노래하는 하리보"를 비롯한 디스코드 음악 봇을 레퍼런스로 기능을 확장해 나갑니다.

---

## 1. 프로젝트 개요

- **목적**: 디스코드 음성 채널에서 유튜브 음원을 검색·재생하는 음악 봇
- **언어/런타임**: Python 3.12
- **핵심 스택**: `discord.py`(py-cord 호환) + `yt-dlp` + `ffmpeg` + `PyNaCl`(opus)
- **봇 초대 링크**: README.md 상단 참고
- **레퍼런스(벤치마킹 대상)**: 노래하는 하리보 등 한국어 디스코드 음악 봇
  - 참고할 UX 요소: 슬래시 명령어, 인터랙티브 버튼/임베드, 재생 컨트롤(일시정지/재개/반복), 가사, 플레이리스트, 자동 추천 등

---

## 2. 디렉터리 / 파일 구조

```
sing_bot/
├── README.md              # 사용자용 기능 설명 (명령어 표, 동작 개요, 설치법)
├── CLAUDE.md              # 이 파일
├── .gitignore             # voiceroom/dico_token.py 등 토큰 제외
└── voiceroom/
    ├── ingribo.py         # ★ 메인 봇 (모든 명령어/재생 로직이 여기에 있음)
    ├── check_token.py     # 초기 학습/테스트용 스크립트 (구버전, 메인 로직과 무관)
    └── dico_token.py      # 봇 토큰 (gitignore 처리됨, 저장소에 없음)
```

- **작업의 99%는 `voiceroom/ingribo.py`에서 이뤄집니다.** 단일 파일에 전체 봇이 구현되어 있습니다.
- `check_token.py`는 초기 discord.py 학습용 잔재이며, 새 기능의 기준으로 삼지 마세요.
- `dico_token.py`는 `from dico_token import Token` 형태로 토큰을 노출합니다. 저장소에는 없으므로 로컬에서 직접 생성해야 합니다.

```python
# voiceroom/dico_token.py (로컬 전용, 절대 커밋 금지)
Token = "여기에_디스코드_봇_토큰"
```

---

## 3. 실행 방법

### 의존성

**macOS**
```bash
brew install ffmpeg opus
pip install -U discord.py yt-dlp pynacl
```

**Windows**
```powershell
winget install Gyan.FFmpeg      # 또는 choco install ffmpeg
pip install -U discord.py yt-dlp pynacl
```

**Linux / Docker**
```bash
apt-get install -y ffmpeg libopus0
pip install -r requirements.txt
```

- **ffmpeg는 PATH에 있어야 합니다.** (`on_ready`에서 `shutil.which('ffmpeg')`로 헬스 체크)
- **opus 라이브러리**(음성 송출용)는 OS마다 로드 방식이 다릅니다:
  - macOS: `ingribo.py`가 `/opt/homebrew/lib/libopus.dylib`를 명시적으로 로드.
  - Windows: `discord.py`에 opus 바이너리가 내장되어 별도 설치 불필요.
  - Linux: `libopus0` 설치 시 `discord.py`가 자동 로드.
  - macOS 전용 로드 코드는 다른 OS에서 **실패해도 `try/except`로 무시**되므로 그대로 실행됩니다.

### 실행
```bash
cd voiceroom
python ingribo.py
```

### 환경 변수
- `YTDLP_COOKIES` (선택): 유튜브 쿠키 파일 경로. 봇 확인/로그인이 걸린 영상 재생 시 사용. 없으면 쿠키 없이 동작.

---

## 4. 아키텍처 / 핵심 동작

### 명령어 (prefix: `!` 또는 봇 멘션)

| 명령어 | 별칭 | 동작 |
|--------|------|------|
| `!join` | `!입장` | 호출자의 음성 채널에 입장 |
| `!out` | `!나가기` | 퇴장 + 큐 초기화 |
| `!p <검색어\|URL>` | — | 검색/URL 재생 또는 큐 추가 |
| `!skip` | — | 현재 곡 스킵, 다음 곡 없으면 퇴장 |
| `!list` | `!queue`, `!q` | 큐 표시 |
| `!remove <번호>` | — | 큐에서 해당 번호 제거(1-based) |
| `!shuffle` | — | 큐 셔플 |
| `!search <검색어>` | — | 상위 5개 결과 + 1️⃣~5️⃣ 리액션 선택 |

### 상태 관리
- **`GuildMusicPlayer`**: 길드(서버)별 재생 상태. `queue`, `playing` 플래그, `search_results`(메시지 ID → 검색 결과) 보유.
- **`players: Dict[guild_id, GuildMusicPlayer]`** + `get_player(guild_id)`로 길드별 격리. **상태는 모두 인메모리이며 봇 재시작 시 소실됩니다.**

### 재생 파이프라인
1. `get_track_info()` / `search_top5()`: yt-dlp 호출을 `asyncio.to_thread`로 비동기 래핑(블로킹 방지). `track_cache`로 동일 쿼리 캐싱.
2. `_extract_with_clients()`: `player_client`를 `tv → web_safari → mweb` 순으로 폴백하며 추출 재시도. 특정 클라이언트에서만 막히는 영상 대응. **`ios`/`android`는 쿠키를 무시(android는 'does not support cookies')하므로 제외.** `web`/`mweb`는 SABR로 'Only images are available'(포맷 0개)가 잦아 **실제 포맷을 안정적으로 반환하는 `tv`(TV HTML5)를 최우선**으로 둠. 또한 yt-dlp가 종료 시 cookiefile을 다시 저장하므로, `:ro` 마운트 충돌·동시 추출 경합을 피하려 매 시도 쿠키를 **쓰기 가능한 임시 파일로 복사**해 사용(원본 보존).
3. `start_playback()`: `FFmpegPCMAudio` + `PCMVolumeTransformer(volume=0.3)`로 재생. **기본 볼륨 30%.** ffmpeg `before_options`에 `-reconnect` 계열 옵션으로 스트리밍 끊김 재연결.
4. `after_play` 콜백 → `handle_after_track()`: 다음 곡 자동 재생. 채널에 사람이 없으면 즉시 퇴장, 정상 종료(재생시간 ≥ duration*0.8) 시 퇴장, 조기 종료면 채널 유지.

### 폴백 로직 (중요)
- `!p`에서 1차 추출 실패 시: URL이면 메타에서 제목을 뽑아 `search_top5`로 **대체 트랙** 검색·검증 후 큐에 추가.
- 후보 트랙은 큐에 넣기 전 `_ytdlp_from_url_sync`로 실재성을 검증.
- 모두 실패하면 "봇 확인/로그인" 안내 메시지 출력.

### EC2/데이터센터 IP 차단 우회 (PO Token)
데이터센터 IP(EC2)는 "Sign in to confirm you're not a bot" 챌린지로 재생이 막힙니다. 대응:
- **bgutil POT 공급자**: `brainicism/bgutil-ytdlp-pot-provider`를 compose 사이드카(포트 4416)로 띄우고, 봇은 `bgutil-ytdlp-pot-provider` pip 플러그인으로 통신. `_ydl_opts_base()`가 `BGUTIL_POT_BASE_URL` 환경변수를 읽어 `extractor_args["youtubepot-bgutilhttp"]["base_url"]`로 주입.
- **클라이언트**: `ios`/`android` 제외(쿠키 무시). `tv/web_safari/mweb` 사용(`tv` 우선 — SABR 회피).
- **쿠키**: `YTDLP_COOKIES`로 Netscape 쿠키 제공(버리는 계정 권장 — 밴 위험).
- **Deno**: n-challenge(서명 해독) JS 런타임. Dockerfile에서 설치.
- 그래도 막히면 최종 수단은 **residential 프록시**(yt-dlp `--proxy`).

### 주요 상수 / 정규식
- `YOUTUBE_URL_REGEX`: 검색어와 URL 구분.
- `EMOJI_CHOICES`: 1️⃣~5️⃣ 리액션.
- `PLAYER_CLIENTS`: 폴백 클라이언트 순서.
- `intents`: `message_content`, `reactions`, `voice_states` 활성화 필요.

---

## 5. 코딩 컨벤션

- **단일 파일 구조 유지**: 현재는 `ingribo.py` 한 파일. 기능이 커지면 모듈 분리를 제안하되, 먼저 사용자와 합의할 것.
- **모든 yt-dlp/블로킹 호출은 `asyncio.to_thread`로 감쌀 것** (이벤트 루프 블로킹 방지).
- **사용자 응답은 `discord.Embed`로 통일.** 색상 관례:
  - 성공/정보: `0x00ff56` (초록)
  - 경고/실패: `0xf66c24` (주황)
  - 로딩/대기: `0x999999` (회색)
- **사용자 대면 텍스트는 한국어.** 코드 주석도 한국어 유지(기존 스타일).
- **로그는 `print()`** + `[태그]` 접두사 (`[YTDLP]`, `[OPUS]`, `[HEALTH]`, `[INFO]`, `[WARN]`). 기존 패턴 유지.
- 길드별 상태는 반드시 `get_player(guild_id)`를 통해 접근.

---

## 6. 작업 시 주의사항

- **토큰/쿠키 등 비밀정보는 절대 커밋하지 말 것.** `dico_token.py`는 `.gitignore`에 등록되어 있음. 새 비밀값이 생기면 환경 변수 또는 gitignore 처리.
- **OS 호환성**: opus 로드 경로(`/opt/homebrew/lib/libopus.dylib`)는 macOS 전용. Linux/Windows 작업 시 분기 처리 필요. (최근 커밋들도 OS 호환성·토큰·쿠키 이슈를 다룸)
- **유튜브 차단/SABR 이슈는 상시 발생.** yt-dlp 버전 의존성이 크므로 재생 실패는 대부분 yt-dlp/클라이언트/쿠키 문제일 가능성이 큼. `-U yt-dlp` 업데이트를 우선 고려.
- **인메모리 상태**: 재시작하면 큐·재생 상태가 사라짐. 영속화(예: 플레이리스트 저장)는 별도 설계 필요.
- 변경 후에는 가능하면 실제 디스코드 서버에서 음성 채널 입장 → `!p` 재생까지 수동 확인.

---

## 7. 배포 (GitHub Actions → AWS EC2, Docker)

`main` push 시 자동 배포되는 CI/CD가 구성되어 있습니다.

### 파이프라인 (`.github/workflows/deploy.yml`)
1. **build-and-push**: 소문자 owner로 이미지명 확정 → Docker 이미지 빌드 → `ghcr.io/<owner>/sing_bot:latest` 및 `:<sha>` 태그로 GHCR push (GHA 캐시 사용).
2. **deploy**: 저장소의 `docker-compose.yml`에서 `<OWNER>` 치환 → **scp로 EC2에 복사** → SSH로 `.env` 생성 → `docker compose pull && up -d` → 구 이미지 prune.
3. `workflow_dispatch`로 수동 트리거 가능.
4. **EC2 최초 세팅은 Docker 설치만** 필요. compose/.env는 매 배포 시 워크플로우가 생성·덮어씀(EC2 수동 수정 금지 — 설정은 저장소 compose에 커밋).

### 관련 파일
| 파일 | 역할 |
|------|------|
| `Dockerfile` | `python:3.12-slim` + `ffmpeg` + `libopus0`. `voiceroom/`를 `/app` 루트로 복사해 `dico_token` import 경로 유지. |
| `docker/entrypoint.sh` | 시작 시 `DISCORD_TOKEN` 환경변수로 `dico_token.py`를 생성 후 `python ingribo.py` 실행. **토큰을 이미지에 굽지 않음.** |
| `docker-compose.yml` | EC2용. `restart: unless-stopped`, `env_file: .env`, bgutil 사이드카, 로그 로테이션. `<OWNER>`는 배포 시 워크플로우가 자동 치환. |
| `requirements.txt` | `discord.py`, `yt-dlp`, `PyNaCl` (ffmpeg/opus는 시스템 패키지). |
| `.dockerignore` | `.git`, `__pycache__`, **`dico_token.py`**, `.env` 등 제외. |

### 비밀값 관리
- **GitHub Secrets**: `DISCORD_TOKEN`, `EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY`. `GITHUB_TOKEN`은 GHCR push/pull용으로 자동 제공.
- **토큰 전달 경로**: `DISCORD_TOKEN` Secret → (deploy 잡이 SSH로) EC2 `~/sing_bot/.env` 생성 → compose `env_file` → 컨테이너 env → entrypoint가 `dico_token.py` 생성.
  - `.env`는 **배포마다 워크플로우가 덮어씀.** 쿠키 등 다른 설정은 `.env`가 아니라 `docker-compose.yml`의 `environment:`에 둘 것.
- **토큰은 어디에도 커밋/빌드 인자로 넣지 않습니다.** Secret → 런타임 환경변수로만 전달.

### 배포 관련 코드 작업 시 주의
- `Dockerfile`은 `voiceroom/` 내부를 `/app` 루트로 복사합니다. import 구조(`from dico_token import Token`, 단일 디렉터리)를 바꾸면 `Dockerfile`/`entrypoint.sh` 경로도 함께 수정해야 합니다.
- 새 파이썬 의존성을 추가하면 **`requirements.txt`에도 반드시 반영**하세요(로컬 `pip install`만으로는 이미지에 안 들어감).
- 토큰을 `dico_token.py` 대신 `os.getenv("DISCORD_TOKEN")`에서 직접 읽도록 리팩터링하면 entrypoint의 파일 생성 단계를 제거할 수 있습니다(권장 개선). 변경 시 로컬 실행 방식도 함께 안내할 것.
- 봇은 아웃바운드 전용 → EC2 보안그룹은 SSH(22)만 개방.

---

## 8. 향후 방향 (하리보 벤치마킹 아이디어)

기능 확장 시 참고할 후보 (구현 전 사용자와 우선순위 합의):
- **슬래시 명령어(`/`)** 및 인터랙티브 버튼/셀렉트 메뉴(재생 컨트롤 UI)
- **일시정지/재개(`!pause`/`!resume`), 반복(`!loop`, 한 곡/전체), 볼륨 조절 명령어**
- 현재 재생 곡 정보 임베드(썸네일/진행바/요청자)
- 플레이리스트 저장·불러오기(영속화 도입 필요)
- 음성 채널 무인 시 자동 퇴장 타이머(현재는 곡 종료 시점 기준)
- 가사 표시, 자동 추천/연속 재생

> 새 기능을 추가할 때는 기존 임베드 색상 관례, 길드별 상태 관리(`GuildMusicPlayer`), 비동기 래핑 패턴을 그대로 따르세요.

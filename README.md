# 🎵 sing_bot — Discord Music Bot (Python)

> 유튜브에서 음악을 검색하고 재생할 수 있는 디스코드 음악 봇입니다.  
> py-cord(discord.py) + yt-dlp + ffmpeg 기반으로 동작하며,  
> 반응형 명령어와 큐 시스템을 지원합니다.
> 
[디스코드 봇 초대 링크](https://discord.com/oauth2/authorize?client_id=1520028046579470366&permissions=3230784&integration_type=0&scope=bot)

---



## 🚀 주요 기능

| 명령어 | 설명 |
|--------|------|
| `!입장` | 현재 사용자가 있는 음성 채널에 봇을 입장시킵니다. |
| `!나가기` | 봇을 음성 채널에서 내보냅니다. 대기열이 모두 초기화됩니다. |
| `!p <검색어>` | 유튜브에서 검색어를 찾아 첫 번째 결과를 재생하거나 큐에 추가합니다. 추가 시 제목·썸네일 정보를 보여줍니다. |
| `!p <유튜브URL>` | 유튜브 링크를 직접 재생합니다. (URL 검증 포함) |
| `!skip` | 현재 재생 중인 곡을 건너뛰고 다음 곡으로 넘어갑니다. 다음 곡이 없으면 퇴장합니다. |
| `!list` / `!queue` | 현재 재생 중인 곡과 대기 중인 곡 리스트를 보여줍니다. |
| `!np` / `!현재곡` | 현재 재생 중인 곡 정보(제목·썸네일·진행바·요청자·반복 모드·대기열)를 보여줍니다. |
| `!remove <번호>` | 대기열에서 해당 번호의 곡을 제거합니다. |
| `!shuffle` | 현재 대기열의 순서를 무작위로 섞습니다. |
| `!loop <모드>` / `!반복` | 반복 모드: `one`(🔂 현재 곡) / `all`(🔁 전체) / `shuffle`(🔀 랜덤) / `off`(끄기). 같은 모드를 다시 입력하면 해제됩니다. |
| `!search <검색어>` | 상위 5개의 검색 결과를 표시하고, 1️⃣~5️⃣ 리액션 중 하나를 선택하면 해당 곡을 큐에 추가합니다. |

---

## 🧠 동작 개요

1. **유튜브 검색 / URL 분석**  
   - `yt-dlp`를 이용해 검색어나 URL로부터 오디오 스트림 정보를 추출합니다.  
   - SABR 스트리밍 이슈 방지를 위해 `compat_opts=["no-youtube-sabr"]` 옵션을 사용합니다.

2. **음원 재생 및 큐 관리**  
   - 봇이 음성 채널에 연결되어 있지 않다면 자동으로 입장합니다.  
   - 새 명령어 입력 시 큐에 곡을 추가하고, 재생 중이 아니라면 자동으로 다음 곡 재생을 시작합니다.  
   - ffmpeg의 `-reconnect` 옵션을 통해 스트리밍 끊김 시 재연결을 시도합니다.

3. **재생 완료 처리**  
   - 곡이 종료되면 `after_play` 콜백을 통해 다음 곡으로 자동 전환됩니다.  
   - 더 이상 재생할 곡이 없다면 봇은 일정 시간 후 자동으로 퇴장합니다.

---

## ⚙️ 설치 및 실행

### 1-a. 의존성 설치 (macOS)
```bash
brew install ffmpeg
brew install opus
pip install -U discord.py yt-dlp pynacl
```

### 1-b. 의존성 설치 (Windows)
```powershell
# 1) ffmpeg 설치 (택1)
winget install Gyan.FFmpeg
#   또는: choco install ffmpeg
#   설치 후 ffmpeg.exe 가 PATH 에 있어야 합니다. (확인: ffmpeg -version)

# 2) 파이썬 패키지 설치
pip install -U discord.py yt-dlp pynacl
```
> **opus 안내**: Windows에서는 `discord.py` 패키지에 opus 바이너리가 포함되어 별도 설치가 필요 없습니다.
> `ingribo.py`의 macOS 전용 opus 로드 경로(`/opt/homebrew/lib/libopus.dylib`)는 로드에 실패해도 `try/except`로 무시되므로 그대로 실행됩니다.

### 2. 봇 토큰 설정
`voiceroom/dico_token.py` 파일을 만들고 디스코드 봇 토큰을 넣습니다. (이 파일은 `.gitignore`로 제외되어 있습니다.)
```python
# voiceroom/dico_token.py
Token = "여기에_디스코드_봇_토큰"
```

### 3. 실행
```bash
cd voiceroom
python ingribo.py
```

---

## 🚀 배포 (GitHub Actions → AWS EC2, Docker)

`main` 브랜치에 push되면 GitHub Actions가 Docker 이미지를 빌드해 **GHCR**(GitHub Container Registry)로 push하고,
EC2에 SSH로 접속해 최신 이미지를 `docker compose`로 무중단에 가깝게 롤아웃합니다.

> 📘 **EC2 인스턴스 생성부터 SSH 키 연결·Secrets 등록까지 처음 설정하는 전체 절차는 [docs/DEPLOY_EC2.md](docs/DEPLOY_EC2.md) 를 참고하세요.** 아래는 요약입니다.

### 구성 파일
| 파일 | 역할 |
|------|------|
| `Dockerfile` | python:3.12-slim + ffmpeg + libopus0 기반 봇 이미지 |
| `docker/entrypoint.sh` | 컨테이너 시작 시 `DISCORD_TOKEN` 환경변수로 `dico_token.py` 생성 (토큰을 이미지에 굽지 않음) |
| `docker-compose.yml` | EC2에서 이미지를 pull해 실행 (`restart: unless-stopped`) |
| `.github/workflows/deploy.yml` | 빌드 → GHCR push → EC2 배포 파이프라인 |

### 최초 1회 EC2 세팅
```bash
# EC2(Ubuntu) 에서 — Docker 설치만 하면 됩니다.
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER   # 재로그인 필요
```
> `docker-compose.yml`(`<OWNER>` 치환 포함)과 `.env`(토큰)는 **배포 시 GitHub Actions가 자동으로 EC2에 생성**합니다. 수동 배치가 필요 없습니다.

> **주의: `.env`와 `docker-compose.yml`은 배포 때마다 워크플로우가 덮어씁니다.** 따라서 쿠키 등 추가 설정은 `docker-compose.yml`의 `environment:`에 두고 저장소에 커밋하세요. (EC2에서 수동 수정하면 다음 배포 때 사라집니다)

### GitHub Secrets 등록 (Settings → Secrets and variables → Actions)
| Secret | 설명 |
|--------|------|
| `DISCORD_TOKEN` | 디스코드 봇 토큰. 배포 시 EC2 `~/sing_bot/.env` 로 생성됨 |
| `EC2_HOST` | EC2 퍼블릭 IP 또는 도메인 |
| `EC2_USER` | SSH 사용자명 (예: `ubuntu`) |
| `EC2_SSH_KEY` | EC2 접속용 개인키(PEM) 전체 내용 |

> `GITHUB_TOKEN`은 Actions가 자동 제공하며 GHCR push/pull에 사용됩니다. (별도 등록 불필요)

### 배포 흐름
1. `main`에 push → `build-and-push` 잡이 이미지 빌드 후 `ghcr.io/<OWNER>/sing_bot:latest` push
2. `deploy` 잡이 EC2에 SSH 접속 → `docker compose pull && up -d` → 이전 이미지 정리
3. 수동 배포가 필요하면 Actions 탭에서 **workflow_dispatch**로 실행

> 봇은 아웃바운드 전용이라 인바운드 포트 개방이 필요 없습니다. EC2 보안그룹은 **SSH(22)만** 열어두면 됩니다.

---

## 🛠️ 트러블슈팅 — EC2에서 노래가 재생되지 않을 때

EC2 같은 **데이터센터 IP는 YouTube 봇 차단**에 걸려 `Sign in to confirm you're not a bot` 오류로 재생이 막힙니다.
이를 위해 배포 구성에 **PO Token(Proof-of-Origin) 공급자**를 사이드카로 포함했습니다.

| 대응 | 적용 위치 |
|------|-----------|
| **bgutil POT 공급자** (`brainicism/bgutil-ytdlp-pot-provider`) 사이드카, 포트 4416 | `docker-compose.yml` |
| 봇이 공급자와 통신 (`BGUTIL_POT_BASE_URL`) | `docker-compose.yml` env + `ingribo.py` |
| 쿠키를 무시하는 `ios` 클라이언트 제외 → `web/mweb/android` 사용 | `ingribo.py` `PLAYER_CLIENTS` |
| n-challenge(서명 해독) JS 런타임 **Deno** 설치 | `Dockerfile` |
| `yt-dlp[default]` + bgutil 플러그인 | `requirements.txt` |

**그래도 막히는 영상(연령제한 등)이 있다면 — 쿠키 추가**
1. 브라우저에서 **버리는 유튜브 계정**으로 로그인 후, 확장 프로그램으로 쿠키를 Netscape 포맷(`cookies.txt`)으로 내보냅니다. (⚠️ 봇 트래픽으로 계정이 밴될 수 있으니 메인 계정 금지)
2. `cookies.txt`를 EC2 `~/sing_bot/`에 둡니다.
3. `docker-compose.yml`의 `volumes`와 `YTDLP_COOKIES` 주석을 해제합니다.

**최종 수단**: 위로도 안 되면 **residential 프록시**를 yt-dlp `--proxy`로 물리는 방법이 가장 확실합니다(유료).

> PO Token은 영상마다 다르고 수명이 짧아(약 12시간) 수동 추출은 비권장 — 사이드카 공급자가 자동 갱신합니다.

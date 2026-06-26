# GitHub Actions → AWS EC2 배포 연결 가이드

이 문서는 `.github/workflows/deploy.yml`이 EC2에 자동 배포되도록 **AWS·GitHub 설정을 처음부터** 연결하는 절차입니다.
완료하면 `main` 브랜치 push만으로 EC2에서 봇이 갱신됩니다.

## 전체 그림

```
git push (main)
   │
   ▼
GitHub Actions (ubuntu 러너)
   ├─ build-and-push : Docker 이미지 빌드 → GHCR push
   └─ deploy
        ├─ docker-compose.yml 렌더(<OWNER> 치환) → scp → EC2
        └─ SSH 접속 → .env 생성 → docker compose pull && up -d
                  │  (SSH 키 = GitHub Secret EC2_SSH_KEY)
                  ▼
              EC2 (Docker)
                ├─ sing-bot 컨테이너
                └─ bgutil-provider 컨테이너 (POT)
```

연결의 핵심은 **① EC2 준비**, **② SSH 키로 GitHub↔EC2 인증**, **③ GitHub Secrets 4개 등록** 세 가지입니다.

---

## 1단계. EC2 인스턴스 준비

1. **인스턴스 생성** (AWS 콘솔 → EC2 → Launch instance)
   - AMI: **Ubuntu Server 22.04 LTS** (또는 24.04)
   - 타입: `t3.small` 이상 권장 (음성 트랜스코딩 + bgutil 사이드카 고려. `t2.micro`는 메모리가 빠듯함)
   - 스토리지: 16GB 이상
2. **Elastic IP 할당** (EC2 → Elastic IPs → Allocate → 인스턴스에 Associate)
   - 재부팅 시 IP가 바뀌지 않도록 고정. 이 IP가 `EC2_HOST`가 됩니다.
3. **보안 그룹 인바운드 규칙**
   - **SSH(22)** 만 허용. 소스는 아래 중 택1:
     - (간단·권장) `0.0.0.0/0` 으로 열되 **반드시 키 기반 인증만** 사용(아래 2단계에서 비밀번호 로그인 비활성). GitHub 호스티드 러너는 IP가 매번 바뀌어 특정 IP로 제한이 어렵습니다.
     - (엄격) GitHub Actions 공개 IP 대역만 허용 — `https://api.github.com/meta` 의 `actions` 목록. 대역이 넓고 자주 바뀌어 유지보수 부담이 큽니다.
   - 봇은 **아웃바운드 전용**이라 그 외 인바운드 포트는 열 필요 없음.

---

## 2단계. 배포 전용 SSH 키 연결

EC2 로그인용 키페어와 별개로, **배포 전용 키**를 만들어 GitHub에만 주는 것을 권장합니다(유출 시 이 키만 폐기).

### 2-1. 로컬에서 키 생성
```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f deploy_key
# 결과: deploy_key(개인키), deploy_key.pub(공개키). 패스프레이즈는 비워둠(자동화용).
```

### 2-2. 공개키를 EC2에 등록
EC2에 접속(최초엔 인스턴스 생성 시 만든 .pem 키 사용)한 뒤:
```bash
# EC2 안에서
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "deploy_key.pub 의 내용 한 줄을 여기에 붙여넣기" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

### 2-3. 비밀번호 로그인 비활성(보안)
```bash
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
```

### 2-4. 개인키는 GitHub Secret 으로
`deploy_key`(개인키) **파일 전체 내용**(`-----BEGIN ...` ~ `-----END ...` 포함)을 복사해 둡니다 → 3단계의 `EC2_SSH_KEY`.

> ⚠️ `deploy_key` 개인키는 절대 저장소에 커밋하지 마세요. GitHub Secret 에만 넣습니다.

---

## 3단계. EC2에 Docker 설치 (최초 1회)

```bash
# EC2(Ubuntu) 안에서
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER     # 적용하려면 로그아웃 후 재접속
docker --version && docker compose version   # 확인
```

> `docker-compose.yml`과 `.env`는 배포 시 워크플로우가 자동 생성하므로 **여기서 만들 필요 없습니다.**

---

## 4단계. GitHub Secrets 등록

저장소 → **Settings → Secrets and variables → Actions → New repository secret** 에서 4개 등록:

| Secret 이름 | 값 | 비고 |
|-------------|-----|------|
| `DISCORD_TOKEN` | 디스코드 봇 토큰 | 배포 시 EC2 `.env`로 생성됨 |
| `EC2_HOST` | EC2 Elastic IP (또는 도메인) | 1단계의 고정 IP |
| `EC2_USER` | `ubuntu` | Ubuntu AMI 기본 사용자 |
| `EC2_SSH_KEY` | `deploy_key` 개인키 전체 내용 | 2-4에서 복사한 값 |

> `GITHUB_TOKEN`은 Actions가 자동 제공하므로 등록 불필요. (GHCR push 및 EC2에서의 pull 인증에 사용)

---

## 5단계. 첫 배포 실행

방법 A. `main`에 아무 커밋이나 push
```bash
git push origin main
```
방법 B. 저장소 **Actions 탭 → Deploy to EC2 → Run workflow**(workflow_dispatch) 수동 실행

---

## 6단계. 배포 확인

1. **GitHub**: Actions 탭에서 `build-and-push` → `deploy` 두 잡이 모두 초록색인지 확인. `deploy` 로그에 렌더된 `docker-compose.yml`과 `compose up` 출력이 보입니다.
2. **EC2**:
   ```bash
   cd ~/sing_bot
   docker compose ps          # sing-bot, bgutil-provider 둘 다 Up 인지
   docker compose logs -f sing-bot
   # 로그에 "봇을 실행합니다" + [HEALTH] ffmpeg/Opus/BGUTIL 줄이 보이면 정상
   ```
3. **디스코드**: 봇이 온라인이 되면 음성 채널에서 `!p <노래>` 로 재생 테스트.

---

## 트러블슈팅

| 증상 | 원인 / 해결 |
|------|-------------|
| `deploy` 잡 SSH 단계에서 timeout/permission denied | `EC2_HOST`(IP) 오타, 보안그룹 22 미개방, `EC2_SSH_KEY` 개인키 내용 누락(BEGIN/END 포함 전체인지), `authorized_keys` 등록 누락 |
| EC2에서 `docker compose pull` 시 `denied`/`unauthorized` | GHCR 패키지가 private이고 권한 부족. 저장소 → Packages 에서 해당 패키지를 repo에 연결하거나, 패키지 가시성을 public 으로 변경. 또는 `GITHUB_TOKEN` 대신 `read:packages` PAT를 별도 Secret으로 사용 |
| 컨테이너는 떴는데 봇 오프라인 | `DISCORD_TOKEN` 값 오류 또는 토큰 재발급 후 미갱신. `docker compose logs sing-bot` 확인 후 Secret 갱신 → 재배포 |
| 노래가 재생 안 됨("Sign in to confirm...") | bgutil 사이드카 동작/네트워크 확인(`docker compose logs bgutil-provider`). 필요 시 쿠키 추가 (README 트러블슈팅 참고) |
| `permission denied while trying to connect to the Docker daemon` | `usermod -aG docker $USER` 후 **재접속** 안 함. 재로그인하거나 `newgrp docker` |

---

## 보안 체크리스트

- [ ] 대화/스크린샷에 노출됐던 봇 토큰은 **Reset Token**으로 재발급했는가
- [ ] `EC2_SSH_KEY`/`DISCORD_TOKEN`은 저장소에 커밋되지 않고 Secret에만 있는가
- [ ] EC2 비밀번호 로그인을 비활성화했는가(키 인증만)
- [ ] 보안그룹은 22 외 불필요한 포트가 닫혀 있는가

# claude-rc

**Telegram ↔ Claude Code 원격 제어 브릿지**

macOS의 iTerm2 tmux 세션에서 실행 중인 Claude Code를 Telegram으로 원격 제어하는 Python 브릿지입니다. 외출 중에도 스마트폰으로 Claude Code에 명령을 보내고 응답을 받을 수 있습니다.

```
Telegram 메시지 → 브릿지 (Python) → tmux send-keys → Claude Code
Claude Code 출력 → tmux capture-pane → 브릿지 → Telegram 응답
```

---

## 주요 기능

- **Telegram → Claude Code 명령 전달**: 스마트폰에서 메시지를 보내면 tmux 세션의 Claude Code로 전달
- **자동 응답 감지**: `❯` 프롬프트 감지로 Claude Code 응답 완료 시점 포착
- **다중 세션 지원**: 여러 tmux 세션 간 동적 전환 (`/switch`)
- **노이즈 필터링**: ANSI 코드, 스피너, UI 잔재 등 완전 제거 후 깔끔한 텍스트 전달
- **세션 영속성**: 재시작 후에도 마지막 활성 세션 자동 복구
- **LaunchAgent 자동 시작**: 시스템 부팅 시 브릿지 자동 실행
- **Claude Code 스킬 통합**: `/claude-rc` 스킬로 대화형 설치

---

## 시작하기

### 필수 요건

- macOS 10.14+
- Python 3.8+
- tmux (`brew install tmux`)
- Telegram 봇 토큰 ([BotFather](https://t.me/BotFather)에서 발급)
- 본인 Telegram Chat ID

### 설치

#### 방법 1: 자동 설치 스크립트 (권장)

```bash
git clone https://github.com/your-username/claude-rc.git
cd claude-rc
./install.sh
```

설치 스크립트가 자동으로:
1. tmux, Python 3 의존성 확인 및 설치
2. Python 가상 환경(venv) 생성 및 패키지 설치
3. `config/config.yaml` 템플릿 생성
4. macOS LaunchAgent 등록 (자동 시작 설정)

#### 방법 2: Claude Code 스킬로 설치

Claude Code 세션에서:

```
/claude-rc
```

대화형 6단계 설치 진행 (토큰 입력, 세션 설정, LaunchAgent 등록 포함)

#### 방법 3: 수동 설치

```bash
git clone https://github.com/your-username/claude-rc.git
cd claude-rc

# 가상환경 생성
python3 -m venv venv
source venv/bin/activate

# 패키지 설치
pip install -r requirements.txt

# 설정 파일 생성
mkdir -p config
cp config/config.example.yaml config/config.yaml
# config/config.yaml 편집
```

---

## 설정

`config/config.yaml` 파일을 편집합니다:

```yaml
telegram:
  bot_token: "YOUR_BOT_TOKEN_HERE"       # BotFather에서 발급한 토큰
  allowed_chat_ids: [YOUR_CHAT_ID]        # 허용할 Telegram Chat ID

tmux:
  session_name: "claude"                  # 연결할 tmux 세션 이름
  auto_create_session: true               # 세션 없으면 자동 생성

bridge:
  output_log: "/tmp/claude-rc-output.log"
  quiet_seconds: 1.5                      # 응답 완료 판단 대기 시간
  max_wait_seconds: 600                   # 최대 대기 시간 (초)
  poll_interval: 0.1                      # 출력 폴링 간격

logging:
  level: "INFO"
  file: "logs/bridge.log"
```

---

## 실행

### 직접 실행

```bash
source venv/bin/activate
python3 main.py
```

### LaunchAgent로 자동 실행 (설치 후 자동 등록)

```bash
# 시작
launchctl load ~/Library/LaunchAgents/com.user.claude-rc.plist

# 중지
launchctl unload ~/Library/LaunchAgents/com.user.claude-rc.plist
```

---

## Telegram 명령어

| 명령어 | 설명 |
|--------|------|
| `/start` | 브릿지 상태 및 연결 정보 표시 |
| `/status` | 현재 tmux 세션 상태 확인 |
| `/sessions` | 연결 가능한 tmux 세션 목록 |
| `/switch <세션명>` | 다른 tmux 세션으로 전환 |
| `/interrupt` | Ctrl+C 전송 (실행 중단) |
| `/cap` | 현재 터미널 화면 캡처 |
| `/help` | 전체 명령어 도움말 |

일반 메시지는 그대로 Claude Code로 전달됩니다.  
숫자(1~5), Enter, 방향키(↑↓), Esc 등 인터랙티브 입력도 지원합니다.

---

## 프로젝트 구조

```
claude-rc/
├── main.py                         # 메인 엔트리포인트
├── install.sh                      # 자동 설치 스크립트
├── install-skill.sh                # Claude Code 스킬 설치
├── requirements.txt                # Python 의존성
├── version.json                    # 버전 정보
├── bridge/
│   ├── tmux_session.py             # tmux 세션 제어 및 출력 파싱
│   └── telegram_bot.py             # Telegram 봇 명령 처리
├── config/
│   └── config.yaml                 # 브릿지 설정 (설치 후 생성)
├── state/
│   └── active_session.txt          # 마지막 활성 세션 저장
├── logs/
│   └── bridge.log                  # 브릿지 실행 로그
└── .claude/
    └── skills/claude-rc/
        └── SKILL.md                # Claude Code 스킬 정의
```

---

## 동작 원리

1. **Telegram 수신**: 사용자 메시지를 Telegram Bot API로 수신
2. **권한 확인**: `allowed_chat_ids` 기반 접근 제어
3. **tmux 전송**: `tmux send-keys`로 활성 세션에 명령 전달
4. **출력 폴링**: `tmux capture-pane`으로 화면 주기적 캡처
5. **완료 감지**: `❯` 프롬프트 출현으로 Claude Code 응답 완료 감지
6. **노이즈 제거**: ANSI 코드, 스피너, UI 잔재 정규식 필터링
7. **Telegram 전송**: 정제된 응답을 최대 4096자 청크로 분할 전송

---

## 의존성

```
python-telegram-bot[asyncio]==21.5
pyyaml==6.0.2
```

---

## 트러블슈팅

**브릿지가 응답하지 않을 때**
```bash
# 로그 확인
tail -f logs/bridge.log

# tmux 세션 확인
tmux list-sessions
```

**tmux 세션을 찾지 못할 때**
```bash
# 설정의 session_name과 실제 세션명 일치 확인
tmux new-session -s claude
```

**LaunchAgent 재시작**
```bash
launchctl unload ~/Library/LaunchAgents/com.user.claude-rc.plist
launchctl load ~/Library/LaunchAgents/com.user.claude-rc.plist
```

---

## 라이선스

MIT License

---

> 제작자: **벡터나인 꿀꿀**

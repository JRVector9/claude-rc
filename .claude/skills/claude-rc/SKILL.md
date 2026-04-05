---
name: claude-rc
version: "1.6.0"
description: "Telegram과 Claude Code(iTerm2 tmux 세션)를 연결하는 브릿지를 설치하고 설정합니다. 사용자가 텔레그램으로 Claude에게 명령을 보내고 답변을 받을 수 있게 합니다. Triggers on: claude-rc, telegram-rc, 텔레그램 브릿지, telegram bridge, telegram iterm, telegram claude. Use when: user wants to control Claude Code via Telegram, set up telegram bot for iTerm2."
---

# /claude-rc — Telegram ↔ Claude Code Bridge 설치 스킬

## Step 0: 업데이트 확인

스킬이 시작되면 **가장 먼저** 아래를 실행한다.

```bash
CURRENT_VERSION="1.6.0"
REMOTE_JSON=$(curl -sf "https://raw.githubusercontent.com/JRVector9/claude-rc/main/version.json" 2>/dev/null || echo "")
```

`REMOTE_JSON`이 비어있으면 (네트워크 오류 등) 업데이트 확인을 건너뛰고 Step 1로 진행한다.

`REMOTE_JSON`이 있으면 아래를 실행해 버전을 비교한다:

```bash
REMOTE_VERSION=$(echo "$REMOTE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['version'])" 2>/dev/null || echo "")
```

`REMOTE_VERSION == CURRENT_VERSION` 이거나 비어있으면 건너뛰고 Step 1로 진행한다.

`REMOTE_VERSION != CURRENT_VERSION` 이면 업데이트가 있다는 뜻이다. 변경사항 3개를 추출한다:

```bash
CHANGES=$(echo "$REMOTE_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for i, c in enumerate(d.get('changes', [])[:3], 1):
    print(f'{i}. {c}')
" 2>/dev/null || echo "")
```

그런 다음 AskUserQuestion 도구로 묻는다:

```
claude-rc 새 버전이 있습니다! (현재: CURRENT_VERSION → 최신: REMOTE_VERSION)

업데이트 내용:
CHANGES

A) 업데이트 — 최신 스킬로 교체 후 재시작
B) 건너뛰기 — 현재 버전으로 계속 진행
```

- **A 선택 시**: 아래를 실행한다
  ```bash
  curl -fsSL "https://raw.githubusercontent.com/JRVector9/claude-rc/main/.claude/skills/claude-rc/SKILL.md" \
    -o ~/.claude/skills/claude-rc/SKILL.md
  ```
  완료 후 다음 메시지를 출력하고 **종료**한다:
  > "스킬이 업데이트됐습니다. `/claude-rc` 를 다시 실행해주세요."

- **B 선택 시**: 그대로 Step 1로 진행한다.

---

## Overview

이 스킬은 Telegram 봇과 iTerm2의 tmux 세션(Claude Code 실행 중)을 연결하는 브릿지를 설치합니다.

**동작 방식:**
```
Telegram 메시지 → 브릿지(Python) → tmux send-keys → Claude Code
Claude Code 출력 → tmux capture-pane → 브릿지 → Telegram 답장
```

**전제 조건:** tmux, Python 3.8+, iTerm2 설치됨

---

## 설치 단계 안내

설치는 아래 6단계로 자동 진행됩니다. 각 단계에서 선택지가 주어지며, 기본값(A)을 선택하면 됩니다.

- **Step 1** — 환경 확인: brew, tmux, Python 3 설치 여부 체크. 없으면 자동 설치 제안.
- **Step 2** — 정보 수집: 설치 경로, 봇 토큰, Chat ID 입력. 채팅창에 직접 붙여넣으면 됨.
- **Step 3** — 파일 생성: 브릿지 코드 6개 파일 자동 생성. 터미널에 Write 작업이 여러 개 표시되지만 클릭 없이 자동 진행됨.
- **Step 4** — 패키지 설치: Python 가상환경 + Telegram 라이브러리 설치. 약 30초 소요.
- **Step 5** — 자동 시작 등록: macOS LaunchAgent에 등록하면 재부팅 후에도 자동 실행됨.
- **Step 6** — 실행 및 완료: tmux 세션 생성, 브릿지 시작, Telegram으로 완료 알림 전송.

---

## 재설치 감지 (Step 1 진입 전)

Step 1로 가기 전, `~/.claude-rc/main.py` 가 존재하는지 확인한다:

```bash
[ -f "$HOME/.claude-rc/main.py" ] && echo "INSTALLED" || echo "FRESH"
```

`INSTALLED` 이면 AskUserQuestion 도구로 묻는다:

```
이미 claude-rc가 설치되어 있습니다.

기존 설치가 감지됐습니다 (~/.claude-rc).
봇 토큰이나 Chat ID를 바꾸거나, 파일 전체를 새로 설치할 수 있습니다.

RECOMMENDATION: A — 설정값만 바꾸는 게 빠릅니다.

A) 설정만 업데이트 (봇 토큰 / Chat ID 재입력 후 브릿지 재시작)
B) 전체 재설치 (기존 파일 덮어쓰기)
C) 취소
```

- **A**: Step 2로 바로 이동 (파일 생성 건너뜀, Step 2 → Step 4 → Step 5 → Step 6)
- **B**: 전체 설치 진행 (Step 1부터)
- **C**: 종료

`FRESH` 이면 그대로 Step 1로 진행한다.

---

## Step 1: 의존성 확인 및 설치

bash 실행 전에 AskUserQuestion 도구로 먼저 묻는다:

```
설치에 필요한 환경을 확인합니다.

brew, tmux, Python 3 — 이 3가지가 있어야 브릿지가 동작합니다.
확인을 위해 터미널 명령 실행 허가를 요청할 것입니다.
팝업이 뜨면 "Yes" 또는 "Yes, and don't ask again"을 클릭해주세요.

A) 확인 시작
B) 취소
```

**B 선택 시** 종료한다.

**A 선택 시** 3가지를 한 번에 확인한다:

```bash
BREW=$(command -v brew >/dev/null 2>&1 && echo "OK" || echo "MISSING")
TMUX=$(command -v tmux >/dev/null 2>&1 && echo "OK" || echo "MISSING")
PY=$(python3 -c "import sys; exit(0 if sys.version_info >= (3,8) else 1)" 2>/dev/null && echo "OK" || echo "MISSING")
echo "brew=$BREW tmux=$TMUX python=$PY"
```

각 항목이 `MISSING` 이면 아래 순서대로 AskUserQuestion 도구로 묻고 설치한다.

### 1-1. Homebrew가 없을 때

```
Homebrew가 설치되어 있지 않습니다.

Homebrew는 macOS용 앱 관리 도구입니다. 명령어 한 줄로 tmux, Python을 설치할 수 있게 해줍니다.
설치에 1~2분 정도 걸립니다.

RECOMMENDATION: A — Homebrew 없이는 다음 단계로 진행할 수 없습니다.

A) 설치하기 (권장)
B) 취소 — 직접 설치 후 다시 실행 (https://brew.sh)
```

- **A**: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"` 실행 후 계속
- **B**: 중단

### 1-2. tmux가 없을 때

```
tmux가 설치되어 있지 않습니다.

tmux는 터미널 세션 관리 도구입니다. Claude Code를 백그라운드에서 계속 켜두면서
Telegram 브릿지가 연결할 수 있게 해주는 핵심 역할을 합니다.
설치에 30초 정도 걸립니다.

RECOMMENDATION: A — brew install tmux 한 줄로 바로 설치됩니다.

A) 설치하기 (권장) — brew install tmux
B) 취소
```

- **A**: `brew install tmux` 실행 후 계속
- **B**: 중단

### 1-3. Python 3.8+가 없을 때

```
Python 3.8 이상이 설치되어 있지 않습니다.

Python은 Telegram ↔ tmux 사이를 연결하는 브릿지 코드를 실행합니다.
설치에 1~2분 정도 걸립니다.

RECOMMENDATION: A — brew install python3 로 바로 설치 가능합니다.

A) 설치하기 (권장) — brew install python3
B) 취소
```

- **A**: `brew install python3` 실행 후 계속
- **B**: 중단

세 가지가 모두 확인되면 Step 2로 진행한다:
> "✅ 환경 확인 완료: brew, tmux, Python 모두 준비됐습니다."

---

## Step 2: 사용자에게 정보 수집

아래 3가지를 순서대로 AskUserQuestion 도구로 질문한다 (한 번에 하나씩).

### 2-1. 설치 경로

```
브릿지 파일을 어디에 설치할지 정합니다.

기본 경로는 ~/.claude-rc 입니다. 특별한 이유가 없다면 기본값을 추천합니다.

RECOMMENDATION: A — 기본 경로로 충분합니다.

A) 기본 경로 사용 (~/.claude-rc)
B) 직접 경로 입력
```

- **A**: `INSTALL_PATH = $HOME/.claude-rc`
- **B**: 경로를 직접 입력받아 사용, `~`는 실제 홈 경로로 치환

### 2-2. Telegram 봇 토큰

AskUserQuestion 도구로 묻는다. **옵션 라벨은 아래 텍스트를 정확히 그대로 쓴다. '(추천)', '(추체)', '(Recommended)' 등 어떤 텍스트도 추가하지 않는다.**

```
Telegram 봇 토큰이 필요합니다.

아직 봇이 없다면 지금 만들어야 합니다 (2분 소요):
  1. Telegram 앱에서 @BotFather 검색 후 채팅 시작
  2. /newbot 전송
  3. 봇 이름 입력 (예: MyClaudeBot)
  4. 봇 사용자 이름 입력 (예: my_claude_bot) — 반드시 _bot으로 끝나야 함
  5. BotFather가 토큰을 발급해줍니다

A) 지금 입력
B) 나중에 입력 — 설치 후 config 파일 직접 수정
```

- **A 선택 시**: 아래 텍스트를 출력하고 사용자의 다음 메시지를 기다린다:
  ```
  봇 토큰을 이 채팅창에 바로 붙여넣어 주세요.
  예시: 1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
  ```
  사용자가 입력한 텍스트를 `BOT_TOKEN` 으로 저장한다.

- **B 선택 시**: `BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"` (플레이스홀더) 로 저장하고 계속 진행한다.
  설치 완료 후 `INSTALL_PATH/config/config.yaml` 에서 직접 수정하도록 안내한다.

### 2-3. Telegram Chat ID

AskUserQuestion 도구로 묻는다. **옵션 라벨은 아래 텍스트를 정확히 그대로 쓴다. '(추천)', '(추체)', '(Recommended)' 등 어떤 텍스트도 추가하지 않는다.**

```
본인의 Telegram Chat ID가 필요합니다.

확인 방법 (1분 소요):
  1. Telegram 앱에서 @userinfobot 검색 후 채팅 시작
  2. /start 전송
  3. 표시된 숫자가 본인의 Chat ID입니다

A) 지금 입력
B) 나중에 입력 — 설치 후 config 파일 직접 수정
```

- **A 선택 시**: 아래 텍스트를 출력하고 사용자의 다음 메시지를 기다린다:
  ```
  Chat ID를 이 채팅창에 입력해주세요.
  예시: 1234567890
  ```
  사용자가 입력한 텍스트를 `CHAT_ID` (정수) 로 저장한다.

- **B 선택 시**: `CHAT_ID = 0` (플레이스홀더) 로 저장하고 계속 진행한다.
  설치 완료 후 `INSTALL_PATH/config/config.yaml` 에서 직접 수정하도록 안내한다.

수집 완료 후 Step 3으로 진행한다.

---

## Step 3: 프로젝트 파일 생성

파일 생성 전에 사용자에게 아래 텍스트를 출력한다:
> "파일 생성을 시작합니다. 자동으로 진행됩니다. 완료될 때까지 기다려 주세요."

**사용자에게 묻지 않고 아래 파일 전체를 한 번에 생성한다. 중간에 확인 질문 없이 완료까지 진행한다.**

**중요: Write 도구를 사용하지 않는다. 모든 파일은 bash cat heredoc으로 생성한다. 이렇게 하면 권한 팝업 없이 자동으로 진행된다.** 각 파일 생성 시 "파일 생성 중: [파일명]..." 텍스트를 출력한다.

`INSTALL_PATH` 디렉토리와 하위 폴더를 생성한다:

```bash
mkdir -p INSTALL_PATH/{bridge,config,logs,state}
```

아래 파일들을 **모두** 해당 경로에 **bash cat heredoc**으로 생성한다.

---

### 파일 1: `INSTALL_PATH/config/config.yaml`

```yaml
telegram:
  bot_token: "BOT_TOKEN_PLACEHOLDER"
  allowed_chat_ids:
    - CHAT_ID_PLACEHOLDER

tmux:
  session_name: "claude"
  auto_create_session: true

bridge:
  output_log: "/tmp/claude-rc-output.log"
  quiet_seconds: 2.5
  max_wait_seconds: 120
  poll_interval: 0.3

logging:
  level: "INFO"
  file: "logs/bridge.log"
```

`BOT_TOKEN_PLACEHOLDER`는 실제 BOT_TOKEN으로, `CHAT_ID_PLACEHOLDER`는 실제 CHAT_ID로 교체한다.

---

### 파일 2: `INSTALL_PATH/bridge/__init__.py`

(빈 파일)

---

### 파일 3: `INSTALL_PATH/bridge/tmux_session.py`

```python
"""
tmux session controller — owns the PTY, iTerm2 just displays via attach.
"""
import asyncio
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

CLAUDE_PROMPT_RE = re.compile(r'^❯\s*$', re.MULTILINE)

_NOISE_RE = re.compile(
    r'^(?:'
    r'[✢✳✶✻✽·⏺\s]*'
    r'|[─═─]{3,}'
    r'|esc\s*to\s*interrupt'
    r'|\?\s*for\s*shortcuts'
    r'|❯\s*.*'
    r')$',
    re.IGNORECASE
)

_STATUS_RE = re.compile(
    r'Elucidating|Actualizing|Thinking|thinking with|running stop hook|stop hook',
    re.IGNORECASE
)

_SPINNER_CHARS = re.compile(r'[✢✳✶✻✽⏺]')


@dataclass
class SessionConfig:
    session_name: str
    output_log: str
    quiet_seconds: float
    max_wait_seconds: float
    poll_interval: float


class TmuxSession:
    def __init__(self, cfg: SessionConfig):
        self.cfg = cfg
        self.lock = asyncio.Lock()
        self._pipe_active = False
        self._last_sent_text = ''

    def session_exists(self) -> bool:
        r = subprocess.run(['tmux', 'has-session', '-t', self.cfg.session_name],
                           capture_output=True)
        return r.returncode == 0

    def create_session(self):
        subprocess.run([
            'tmux', 'new-session', '-d', '-s', self.cfg.session_name,
            '-x', '220', '-y', '50'
        ], check=True)

    def ensure_session(self):
        if not self.session_exists():
            self.create_session()

    def start_pipe(self):
        Path(self.cfg.output_log).touch()
        subprocess.run([
            'tmux', 'pipe-pane', '-t', self.cfg.session_name,
            f'cat >> {self.cfg.output_log}'
        ])
        self._pipe_active = True

    def list_sessions(self) -> list[dict]:
        r = subprocess.run(
            ['tmux', 'list-sessions', '-F',
             '#{session_name}|#{session_windows}|#{session_attached}'],
            capture_output=True, text=True
        )
        sessions = []
        for line in r.stdout.strip().splitlines():
            parts = line.split('|')
            if len(parts) == 3:
                sessions.append({
                    'name': parts[0], 'windows': parts[1],
                    'attached': parts[2] == '1'
                })
        return sessions

    def capture_pane(self, scrollback: int = 500) -> list[str]:
        r = subprocess.run(
            ['tmux', 'capture-pane', '-t', self.cfg.session_name,
             '-p', '-S', f'-{scrollback}'],
            capture_output=True, text=True
        )
        return r.stdout.splitlines()

    def _capture_anchor(self) -> str:
        lines = self.capture_pane(scrollback=100)
        for line in reversed(lines):
            s = line.strip()
            if s and not _NOISE_RE.match(s) and not _STATUS_RE.search(s):
                return s
        return "__START__"

    def capture_screenshot(self) -> str:
        lines = self.capture_pane(scrollback=200)
        return '\n'.join(lines).strip()

    async def send(self, text: str) -> tuple[int, str]:
        async with self.lock:
            self.ensure_session()
            if not self._pipe_active:
                self.start_pipe()
            anchor = self._capture_anchor()
            log_offset = self._log_size()
            self._last_sent_text = text.strip()
            subprocess.run([
                'tmux', 'send-keys', '-t', self.cfg.session_name, text, 'Enter'
            ])
            return log_offset, anchor

    async def send_key(self, key: str):
        async with self.lock:
            self.ensure_session()
            subprocess.run(['tmux', 'send-keys', '-t', self.cfg.session_name, key])

    async def send_interrupt(self):
        async with self.lock:
            subprocess.run(['tmux', 'send-keys', '-t', self.cfg.session_name, 'C-c'])

    async def wait_for_response(self, log_offset: int, anchor: str) -> str:
        start = time.time()
        last_size = log_offset
        last_change = time.time()
        while True:
            await asyncio.sleep(self.cfg.poll_interval)
            raw = self._read_log_from(log_offset)
            size = len(raw)
            if size > 0 and CLAUDE_PROMPT_RE.search(raw[-500:]):
                await asyncio.sleep(0.4)
                return self._extract_response(anchor)
            if size != last_size:
                last_size = size
                last_change = time.time()
            elif size > 0 and (time.time() - last_change) > self.cfg.quiet_seconds:
                return self._extract_response(anchor)
            if time.time() - start > self.cfg.max_wait_seconds:
                return self._extract_response(anchor) or "(응답 시간 초과)"

    def _extract_response(self, anchor: str) -> str:
        all_lines = self.capture_pane(scrollback=500)
        if anchor == "__START__":
            new_lines = all_lines
        else:
            anchor_idx = -1
            for i in range(len(all_lines) - 1, -1, -1):
                if all_lines[i].strip() == anchor:
                    anchor_idx = i
                    break
            new_lines = all_lines[anchor_idx + 1:] if anchor_idx >= 0 else all_lines[-50:]
        new_lines = self._skip_sent_echo(new_lines, self._last_sent_text)
        return self._clean_lines(new_lines)

    def _skip_sent_echo(self, lines: list[str], sent: str) -> list[str]:
        """Skip lines that are the user's echoed input (appears plain text in Claude Code's chat UI)."""
        if not sent:
            return lines
        remaining = sent
        result_start = 0
        for i, line in enumerate(lines):
            s = line.strip()
            if s.startswith('❯'):
                s = s[1:].strip()
            if not s:
                result_start = i + 1
                continue
            if remaining.startswith(s):
                remaining = remaining[len(s):].strip()
                result_start = i + 1
                if not remaining:
                    break
            elif s in remaining:
                remaining = ''
                result_start = i + 1
                break
            else:
                break
        return lines[result_start:]

    def _clean_lines(self, lines: list[str]) -> str:
        cleaned = []
        for line in lines:
            s = line.rstrip()
            if _NOISE_RE.match(s.strip()):
                continue
            if _STATUS_RE.search(s):
                continue
            s = _SPINNER_CHARS.sub('', s).strip()
            cleaned.append(s if s else '')
        result = []
        prev_blank = False
        for line in cleaned:
            if line == '':
                if not prev_blank:
                    result.append('')
                prev_blank = True
            else:
                result.append(line)
                prev_blank = False
        return '\n'.join(result).strip()

    def _log_size(self) -> int:
        try:
            return os.path.getsize(self.cfg.output_log)
        except FileNotFoundError:
            return 0

    def _read_log_from(self, offset: int) -> str:
        try:
            with open(self.cfg.output_log, 'rb') as f:
                f.seek(offset)
                return f.read().decode('utf-8', errors='replace')
        except FileNotFoundError:
            return ""
```

---

### 파일 4: `INSTALL_PATH/bridge/telegram_bot.py`

```python
"""
Telegram bot — receives messages, routes to tmux session, returns output.
"""
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from .tmux_session import TmuxSession

logger = logging.getLogger(__name__)

MAX_MSG_LEN = 4096

SHORTCUT_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("1"), KeyboardButton("2"),
         KeyboardButton("3"), KeyboardButton("4")],
        [KeyboardButton("↵ Enter"), KeyboardButton("↑"),
         KeyboardButton("↓"), KeyboardButton("⎋ Esc")],
        [KeyboardButton("/cap")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

KEY_MAP = {
    "↵ Enter": "Enter",
    "↑":       "Up",
    "↓":       "Down",
    "⎋ Esc":   "Escape",
}


class TelegramBot:
    def __init__(self, token: str, allowed_chat_ids: list[int], session: TmuxSession):
        self.token = token
        self.allowed_chat_ids = set(allowed_chat_ids)
        self.session = session
        self.app = None

    def build(self):
        self.app = Application.builder().token(self.token).build()
        self.app.add_handler(CommandHandler("start",     self._cmd_start))
        self.app.add_handler(CommandHandler("status",    self._cmd_status))
        self.app.add_handler(CommandHandler("sessions",  self._cmd_sessions))
        self.app.add_handler(CommandHandler("interrupt", self._cmd_interrupt))
        self.app.add_handler(CommandHandler("cap",       self._cmd_cap))
        self.app.add_handler(CommandHandler("help",      self._cmd_help))
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )
        return self

    def run(self):
        self.app.run_polling(drop_pending_updates=True)

    def _is_allowed(self, update: Update) -> bool:
        return update.effective_chat.id in self.allowed_chat_ids

    async def _reject(self, update: Update):
        await update.message.reply_text("Unauthorized.")
        logger.warning("Rejected chat_id=%s", update.effective_chat.id)

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update): return await self._reject(update)
        await update.message.reply_text(
            "claude-rc 연결됨.\n메시지를 보내면 Claude Code로 전달됩니다.",
            reply_markup=SHORTCUT_KEYBOARD,
        )

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update): return await self._reject(update)
        exists = self.session.session_exists()
        pipe   = self.session._pipe_active
        await update.message.reply_text(
            f"tmux 세션: {'실행 중' if exists else '없음'}\n"
            f"출력 파이프: {'연결됨' if pipe else '끊김'}",
            reply_markup=SHORTCUT_KEYBOARD,
        )

    async def _cmd_sessions(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update): return await self._reject(update)
        sessions = self.session.list_sessions()
        if not sessions:
            return await update.message.reply_text("실행 중인 tmux 세션 없음")
        lines = []
        for s in sessions:
            attached = "연결됨" if s['attached'] else "분리됨"
            target   = " ← 현재" if s['name'] == self.session.cfg.session_name else ""
            lines.append(f"• {s['name']}  windows:{s['windows']}  {attached}{target}")
        await update.message.reply_text("\n".join(lines), reply_markup=SHORTCUT_KEYBOARD)

    async def _cmd_interrupt(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update): return await self._reject(update)
        await self.session.send_interrupt()
        await update.message.reply_text("Ctrl+C 전송됨", reply_markup=SHORTCUT_KEYBOARD)

    async def _cmd_cap(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update): return await self._reject(update)
        screen = self.session.capture_screenshot()
        if not screen:
            return await update.message.reply_text("(화면 비어있음)")
        for chunk in _split(screen, MAX_MSG_LEN):
            await update.message.reply_text(
                chunk,
                reply_markup=SHORTCUT_KEYBOARD,
            )

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update): return await self._reject(update)
        await update.message.reply_text(
            "/status     — 브릿지 상태\n"
            "/sessions   — tmux 세션 목록\n"
            "/interrupt  — Ctrl+C\n"
            "/cap        — 현재 화면 캡처\n"
            "/help       — 이 메시지\n\n"
            "일반 텍스트 → Claude Code로 전달",
            reply_markup=SHORTCUT_KEYBOARD,
        )

    async def _handle_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update): return await self._reject(update)
        text = update.message.text.strip()
        if not text:
            return

        if text in KEY_MAP:
            key = KEY_MAP[text]
            if key:
                await self.session.send_key(key)
                await update.message.reply_text(f"[{text}] 전송됨", reply_markup=SHORTCUT_KEYBOARD)
            return

        if text in ("1", "2", "3", "4"):
            await self.session.send_key(text)
            await update.message.reply_text(f"[{text}] 전송됨", reply_markup=SHORTCUT_KEYBOARD)
            return

        thinking_msg = await update.message.reply_text("typing...", reply_markup=SHORTCUT_KEYBOARD)
        try:
            log_offset, anchor = await self.session.send(text)
            response = await self.session.wait_for_response(log_offset, anchor)
        except Exception as e:
            logger.exception("session error")
            await thinking_msg.edit_text(f"오류: {e}")
            return

        await thinking_msg.delete()
        if not response:
            await update.message.reply_text("(응답 없음)", reply_markup=SHORTCUT_KEYBOARD)
            return
        for chunk in _split(response, MAX_MSG_LEN):
            await update.message.reply_text(
                f"```\n{chunk}\n```", parse_mode="Markdown",
                reply_markup=SHORTCUT_KEYBOARD,
            )


def _split(text: str, size: int) -> list[str]:
    return [text[i:i+size] for i in range(0, len(text), size)]
```

---

### 파일 5: `INSTALL_PATH/requirements.txt`

```
python-telegram-bot==21.5
pyyaml==6.0.2
```

---

### 파일 6: `INSTALL_PATH/main.py`

```python
#!/usr/bin/env python3
import asyncio
import logging
import sys
from pathlib import Path
import yaml
from bridge.tmux_session import TmuxSession, SessionConfig
from bridge.telegram_bot import TelegramBot


def load_config(path: str = "config/config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def setup_logging(cfg: dict):
    log_file = cfg.get("logging", {}).get("file", "logs/bridge.log")
    level = cfg.get("logging", {}).get("level", "INFO")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ]
    )


def main():
    cfg = load_config()
    setup_logging(cfg)
    logger = logging.getLogger("main")
    logger.info("claude-rc starting")

    session_cfg = SessionConfig(
        session_name=cfg["tmux"]["session_name"],
        output_log=cfg["bridge"]["output_log"],
        quiet_seconds=cfg["bridge"]["quiet_seconds"],
        max_wait_seconds=cfg["bridge"]["max_wait_seconds"],
        poll_interval=cfg["bridge"]["poll_interval"],
    )
    session = TmuxSession(session_cfg)

    if cfg["tmux"].get("auto_create_session") and not session.session_exists():
        session.create_session()

    session.start_pipe()
    logger.info("tmux pipe-pane active → %s", session_cfg.output_log)

    asyncio.set_event_loop(asyncio.new_event_loop())
    bot = TelegramBot(
        token=cfg["telegram"]["bot_token"],
        allowed_chat_ids=cfg["telegram"]["allowed_chat_ids"],
        session=session,
    ).build()

    logger.info("Telegram bot polling started")
    bot.run()


if __name__ == "__main__":
    main()
```

---

## Step 4: 의존성 설치

Python 가상환경을 만들고 필요한 패키지 2개(Telegram 라이브러리, YAML 파서)를 설치한다.
약 30초 소요된다:

```bash
cd INSTALL_PATH
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
```

완료되면 Step 5로 진행한다:
> "✅ 패키지 설치 완료"

---

## Step 5: LaunchAgent 등록

plist를 생성하기 전에 AskUserQuestion 도구로 묻는다:

```
브릿지를 시스템 자동 시작에 등록합니다.

macOS의 자동 시작 관리자(LaunchAgent)에 브릿지를 등록하면:
• 지금 바로 백그라운드에서 브릿지가 시작됩니다
• Mac을 재시작해도 자동으로 켜집니다
• 브릿지가 예기치 않게 종료되면 자동으로 재시작됩니다

RECOMMENDATION: A — 이 단계를 건너뛰면 매번 수동으로 브릿지를 실행해야 합니다.

A) 등록하기 (권장)
B) 건너뛰기 — 수동 실행만 사용 (Step 6으로 이동)
```

**A 선택 시** — Write 도구가 아닌 **bash cat heredoc**으로 plist를 생성한다.
(Write 도구는 `~/Library/LaunchAgents/` 경로에 쓰기 실패할 수 있으므로 bash를 사용한다.)
`INSTALL_PATH`는 실제 경로로 치환한다:

```bash
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.user.claude-rc.plist << 'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.claude-rc</string>
    <key>ProgramArguments</key>
    <array>
        <string>INSTALL_PATH/.venv/bin/python3</string>
        <string>INSTALL_PATH/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>INSTALL_PATH</string>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>INSTALL_PATH/logs/launchd-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>INSTALL_PATH/logs/launchd-stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
PLIST_EOF
```
단, heredoc의 `INSTALL_PATH`는 실제 경로로 치환하여 실행한다 (예: `/Users/username/.claude-rc`).

---

## Step 6: 자동 시작 및 완료

사용자에게 묻지 않고 아래를 순서대로 직접 실행한다.

### 6-1. tmux 세션 생성 및 Claude Code 실행

```bash
# 기존 세션이 있으면 건너뜀
tmux has-session -t claude 2>/dev/null || tmux new-session -d -s claude -x 220 -y 50
# PATH를 포함해서 Claude Code 실행 (경로 문제 방지)
tmux send-keys -t claude "export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:\$PATH && claude" Enter
# 3초 대기 후 실제로 실행됐는지 확인
sleep 3
tmux capture-pane -t claude -p | tail -5
```

### 6-2. LaunchAgent 로드 (브릿지 즉시 시작)

```bash
# 기존에 로드된 경우 먼저 언로드
launchctl unload ~/Library/LaunchAgents/com.user.claude-rc.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.user.claude-rc.plist
```

`RunAtLoad=true` 이므로 로드 즉시 브릿지가 백그라운드에서 시작된다.
3초 대기 후 브릿지가 정상 실행 중인지 확인:

```bash
sleep 3
launchctl list | grep claude-rc
```

### 6-3. Telegram으로 설치 완료 메시지 전송

사용자에게 묻지 않고 바로 실행한다.
`BOT_TOKEN`과 `CHAT_ID`는 Step 2에서 수집한 실제 값으로 치환한다:

```bash
curl -s -X POST "https://api.telegram.org/botBOT_TOKEN/sendMessage" \
  -d "chat_id=CHAT_ID" \
  --data-urlencode "text=claude-rc 설치 완료!

Telegram에서 바로 사용할 수 있습니다.
먼저 /start 를 눌러 연결을 확인하세요.

[사용 방법]
- 텍스트 입력 → Claude Code로 전달
- /start   — 연결 확인 (여기서 시작)
- /status  — 브릿지 상태 확인
- /cap     — 현재 화면 캡처
- /interrupt — Ctrl+C
- /help    — 도움말

[Claude 터미널 보기]
터미널에서 아래 명령어로 Claude Code 화면을 볼 수 있습니다:
  tmux attach -t claude
  (빠져나오기: Ctrl+B, D)"
```

### 6-4. 최종 안내 (단 하나)

Claude Code 채팅창에 다음 메시지 하나만 출력한다:

```
설치 완료! Telegram에 사용 방법 안내를 보냈습니다.

  경로: INSTALL_PATH
  세션: claude (tmux)

Claude Code 터미널 보기:  tmux attach -t claude
Telegram에서 /start 눌러서 연결 확인해보세요.
```

---

## 주의사항

- 이 스킬은 macOS + iTerm2 전용이다
- 봇 토큰은 @BotFather, chat ID는 @userinfobot에서 확인

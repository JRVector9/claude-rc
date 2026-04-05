---
name: telegram-rc
description: "Telegram과 Claude Code(iTerm2 tmux 세션)를 연결하는 브릿지를 설치하고 설정합니다. 사용자가 텔레그램으로 Claude에게 명령을 보내고 답변을 받을 수 있게 합니다. Triggers on: telegram-rc, 텔레그램 브릿지, telegram bridge, telegram iterm, telegram claude. Use when: user wants to control Claude Code via Telegram, set up telegram bot for iTerm2."
---

# /telegram-rc — Telegram ↔ Claude Code Bridge 설치 스킬

## Overview

이 스킬은 Telegram 봇과 iTerm2의 tmux 세션(Claude Code 실행 중)을 연결하는 브릿지를 설치합니다.

**동작 방식:**
```
Telegram 메시지 → 브릿지(Python) → tmux send-keys → Claude Code
Claude Code 출력 → tmux capture-pane → 브릿지 → Telegram 답장
```

**전제 조건:** tmux, Python 3.8+, iTerm2 설치됨

---

## Step 1: 의존성 확인 및 설치

아래 순서로 각 도구를 확인하고, 없으면 사용자에게 설치 여부를 묻는다.

### 1-1. Homebrew 확인

```bash
command -v brew && echo "brew OK" || echo "NOT_FOUND"
```

brew가 없으면:
> "Homebrew가 설치되어 있지 않습니다. tmux와 Python 설치에 필요합니다.
> 설치하겠습니까? (yes / no)"

- **yes**: 아래 명령 실행
  ```bash
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  ```
  완료 후 다음 단계로 진행.
- **no**: "Homebrew 없이는 자동 설치가 어렵습니다. https://brew.sh 에서 수동 설치 후 다시 실행해주세요." 안내하고 중단.

### 1-2. tmux 확인

```bash
command -v tmux && tmux -V || echo "NOT_FOUND"
```

tmux가 없으면:
> "tmux가 설치되어 있지 않습니다. tmux는 터미널 세션 관리에 필요합니다.
> 설치하겠습니까? (yes / no)"

- **yes**: 실행
  ```bash
  brew install tmux
  ```
  설치 완료 후 `tmux -V` 로 확인하고 다음 단계로 진행.
- **no**: "tmux 없이는 브릿지를 실행할 수 없습니다." 안내하고 중단.

### 1-3. Python 3.8+ 확인

```bash
python3 --version 2>/dev/null || echo "NOT_FOUND"
```

Python이 없거나 3.8 미만이면:
> "Python 3.8 이상이 설치되어 있지 않습니다.
> 설치하겠습니까? (yes / no)"

- **yes**: 실행
  ```bash
  brew install python3
  ```
  완료 후 `python3 --version` 으로 확인하고 다음 단계로 진행.
- **no**: "Python 없이는 브릿지를 실행할 수 없습니다." 안내하고 중단.

세 가지가 모두 확인되면:
> "✅ 환경 확인 완료: brew, tmux, Python 모두 준비됐습니다."

---

## Step 2: 사용자에게 정보 수집

아래 3가지를 순서대로 질문한다 (한 번에 하나씩):

1. **설치 경로** (기본값: `~/.claude-rc`)
   - "설치 경로를 입력하세요 (기본값: ~/.claude-rc, 그냥 Enter시 기본값 사용)"

2. **Telegram 봇 토큰**
   - "@BotFather 에서 받은 봇 토큰을 입력하세요"
   - 형식 예시: `1234567890:ABCdefGHI...`

3. **Telegram Chat ID**
   - "본인의 Telegram Chat ID를 입력하세요 (@userinfobot 에서 확인 가능)"
   - 형식 예시: `7598341229`

수집한 값을 변수로 기억:
- `INSTALL_PATH` = 입력값 (없으면 `~/.claude-rc`, `~`는 실제 홈 경로로 치환)
- `BOT_TOKEN` = 입력값
- `CHAT_ID` = 입력값 (정수)

---

## Step 3: 프로젝트 파일 생성

`INSTALL_PATH` 디렉토리와 하위 폴더를 생성한다:

```bash
mkdir -p INSTALL_PATH/{bridge,config,logs,state}
```

그런 다음 아래 파일들을 **정확히** 해당 경로에 Write 도구로 생성한다.

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
        return self._clean_lines(new_lines)

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
        [KeyboardButton("📺 /cap")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

KEY_MAP = {
    "↵ Enter": "Enter",
    "↑":       "Up",
    "↓":       "Down",
    "⎋ Esc":   "Escape",
    "📺 /cap":  None,
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
            f"tmux 세션: {'✅ 실행 중' if exists else '❌ 없음'}\n"
            f"출력 파이프: {'✅ 연결됨' if pipe else '❌ 끊김'}",
            reply_markup=SHORTCUT_KEYBOARD,
        )

    async def _cmd_sessions(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update): return await self._reject(update)
        sessions = self.session.list_sessions()
        if not sessions:
            return await update.message.reply_text("실행 중인 tmux 세션 없음")
        lines = []
        for s in sessions:
            attached = "👁 연결됨" if s['attached'] else "분리됨"
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
                f"```\n{chunk}\n```", parse_mode="Markdown",
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

        if text == "📺 /cap":
            return await self._cmd_cap(update, ctx)

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

        thinking_msg = await update.message.reply_text("⏳", reply_markup=SHORTCUT_KEYBOARD)
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

```bash
cd INSTALL_PATH
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
```

---

## Step 5: LaunchAgent 등록

아래 plist를 `~/Library/LaunchAgents/com.user.claude-rc.plist`에 생성한다.
`INSTALL_PATH`는 실제 경로로 치환한다:

```xml
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
    <false/>
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
```

---

## Step 6: 완료 안내

설치가 완료되면 사용자에게 다음을 안내한다:

```
✅ claude-rc 설치 완료!

─── 시작 방법 ───────────────────────────

1. tmux 세션에 Claude Code 실행:
   tmux new -s claude
   (세션 안에서) claude

2. iTerm2에서 연결해서 보기:
   tmux attach -t claude

3. 브릿지 시작:
   cd INSTALL_PATH
   .venv/bin/python3 main.py

4. Telegram에서 /start 전송

─── 브릿지 명령어 ────────────────────────
/status    — 연결 상태
/sessions  — tmux 세션 목록
/interrupt — Ctrl+C
/cap       — 현재 화면 캡처
/help      — 도움말

키보드 버튼: 1 2 3 4 | Enter ↑ ↓ Esc | 📺/cap
```

LaunchAgent로 자동 시작하려면:
```bash
launchctl load ~/Library/LaunchAgents/com.user.claude-rc.plist
```

---

## 주의사항

- 이 스킬은 macOS + iTerm2 전용이다
- tmux가 없으면 `brew install tmux` 안내
- Python 3.8 미만이면 업그레이드 안내
- 봇 토큰은 @BotFather, chat ID는 @userinfobot에서 확인
- 이미 설치된 경우(`INSTALL_PATH/main.py` 존재): config만 업데이트하고 재시작 안내

## 재설치/업데이트 감지

스킬 시작 시 `INSTALL_PATH/main.py`가 이미 존재하는지 확인한다.
- 존재하면: "이미 설치됨. 봇 토큰/Chat ID만 업데이트할까요?" 질문
- 없으면: 전체 설치 진행

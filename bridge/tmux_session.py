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
        self.active_session = cfg.session_name
        self.lock = asyncio.Lock()
        self._pipe_active = False
        self._last_sent_text = ''

    def switch_to(self, session_name: str) -> bool:
        """Switch active session. Returns True if session exists."""
        r = subprocess.run(['tmux', 'has-session', '-t', session_name], capture_output=True)
        if r.returncode != 0:
            return False
        # Stop pipe on old session
        if self._pipe_active:
            subprocess.run(['tmux', 'pipe-pane', '-t', self.active_session], capture_output=True)
            self._pipe_active = False
        self.active_session = session_name
        self._last_sent_text = ''
        return True

    def session_exists(self) -> bool:
        r = subprocess.run(['tmux', 'has-session', '-t', self.active_session],
                           capture_output=True)
        return r.returncode == 0

    def create_session(self):
        subprocess.run([
            'tmux', 'new-session', '-d', '-s', self.active_session,
            '-x', '220', '-y', '50'
        ], check=True)

    def ensure_session(self):
        if not self.session_exists():
            self.create_session()

    def start_pipe(self):
        Path(self.cfg.output_log).touch()
        subprocess.run([
            'tmux', 'pipe-pane', '-t', self.active_session,
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
            ['tmux', 'capture-pane', '-t', self.active_session,
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
                'tmux', 'send-keys', '-t', self.active_session, text, 'Enter'
            ])
            return log_offset, anchor

    async def send_key(self, key: str):
        async with self.lock:
            self.ensure_session()
            subprocess.run(['tmux', 'send-keys', '-t', self.active_session, key])

    async def send_interrupt(self):
        async with self.lock:
            subprocess.run(['tmux', 'send-keys', '-t', self.active_session, 'C-c'])

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

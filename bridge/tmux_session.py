"""
tmux session controller — owns the PTY, iTerm2 just displays via attach.
"""
import asyncio
import logging
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

CLAUDE_PROMPT_RE = re.compile(r'^❯\s*$', re.MULTILINE)
SESSION_NAME_RE = re.compile(r'^[a-zA-Z0-9_\-]{1,50}$')
_DANGEROUS_CTRL = re.compile(r'\bC-[dDzZ]\b')

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

    @property
    def pipe_active(self) -> bool:
        return self._pipe_active

    async def switch_to(self, session_name: str) -> bool:
        """Switch active session. Returns True if session exists."""
        if not SESSION_NAME_RE.match(session_name):
            return False
        r = await asyncio.to_thread(
            subprocess.run, ['tmux', 'has-session', '-t', session_name],
            capture_output=True
        )
        if r.returncode != 0:
            return False
        async with self.lock:
            if self._pipe_active:
                await asyncio.to_thread(
                    subprocess.run,
                    ['tmux', 'pipe-pane', '-t', self.active_session],
                    capture_output=True
                )
                self._pipe_active = False
            self.active_session = session_name
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
            try:
                open(self.cfg.output_log, 'w').close()  # clear stale log for new session
            except OSError:
                pass
            self.create_session()
            self._pipe_active = False

    def start_pipe(self):
        Path(self.cfg.output_log).touch()
        r = subprocess.run([
            'tmux', 'pipe-pane', '-t', self.active_session,
            f'cat >> {shlex.quote(self.cfg.output_log)}'
        ], capture_output=True)
        if r.returncode != 0:
            logger.warning("pipe-pane failed: %s", r.stderr.decode(errors='replace'))
            return
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

    async def send(self, text: str) -> tuple[int, str, str]:
        if _DANGEROUS_CTRL.search(text):
            raise ValueError("허용되지 않은 제어 문자입니다.")
        sent = text.strip()
        async with self.lock:
            await asyncio.to_thread(self.ensure_session)
            if not self._pipe_active:
                await asyncio.to_thread(self.start_pipe)
            anchor = await asyncio.to_thread(self._capture_anchor)
            log_offset = self._log_size()
            # -l sends text literally, preventing tmux key name interpretation
            await asyncio.to_thread(
                subprocess.run,
                ['tmux', 'send-keys', '-t', self.active_session, '-l', text]
            )
            await asyncio.to_thread(
                subprocess.run,
                ['tmux', 'send-keys', '-t', self.active_session, 'Enter']
            )
        return log_offset, anchor, sent

    async def send_key(self, key: str):
        async with self.lock:
            await asyncio.to_thread(self.ensure_session)
            await asyncio.to_thread(
                subprocess.run,
                ['tmux', 'send-keys', '-t', self.active_session, key]
            )

    async def send_interrupt(self):
        async with self.lock:
            await asyncio.to_thread(
                subprocess.run,
                ['tmux', 'send-keys', '-t', self.active_session, 'C-c']
            )

    async def wait_for_response(self, log_offset: int, anchor: str, sent_text: str) -> str:
        start = time.time()
        last_size = log_offset
        last_change = time.time()
        while True:
            await asyncio.sleep(self.cfg.poll_interval)
            size, tail = self._read_log_tail(log_offset)
            if tail and CLAUDE_PROMPT_RE.search(tail):
                await asyncio.sleep(0.4)
                return self._extract_response(anchor, sent_text)
            if size != last_size:
                last_size = size
                last_change = time.time()
            elif size > log_offset and (time.time() - last_change) > self.cfg.quiet_seconds:
                return self._extract_response(anchor, sent_text)
            if time.time() - start > self.cfg.max_wait_seconds:
                return self._extract_response(anchor, sent_text) or "(응답 시간 초과)"

    def _extract_response(self, anchor: str, sent_text: str) -> str:
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
        new_lines = self._skip_sent_echo(new_lines, sent_text)
        return self._clean_lines(new_lines)

    def _skip_sent_echo(self, lines: list[str], sent: str) -> list[str]:
        """Skip lines that are the user's echoed input."""
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
        result = []
        prev_blank = False
        for line in lines:
            s = line.rstrip()
            if _NOISE_RE.match(s.strip()) or _STATUS_RE.search(s):
                continue
            s = _SPINNER_CHARS.sub('', s).strip()
            if s == '':
                if not prev_blank:
                    result.append('')
                prev_blank = True
            else:
                result.append(s)
                prev_blank = False
        return '\n'.join(result).strip()

    def _log_size(self) -> int:
        try:
            return os.path.getsize(self.cfg.output_log)
        except FileNotFoundError:
            return 0

    def _read_log_tail(self, offset: int, tail_bytes: int = 1024) -> tuple[int, str]:
        """Returns (total_size, tail_text) — reads only the last tail_bytes after offset."""
        try:
            with open(self.cfg.output_log, 'rb') as f:
                f.seek(0, 2)
                size = f.tell()
                read_from = max(offset, size - tail_bytes)
                f.seek(read_from)
                return size, f.read().decode('utf-8', errors='replace')
        except FileNotFoundError:
            return offset, ""

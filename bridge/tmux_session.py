"""
tmux session controller — owns the PTY, terminal just displays via attach.
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

# ANSI / terminal escape sequence 제거
# CSI sequences, single-char ESC, OSC sequences (title 등) 모두 포함
_ANSI_ESC = re.compile(
    r'\x1b(?:'
    r'\][^\x07\x1b]*(?:\x07|\x1b\\)'   # OSC: ESC ] ... BEL or ST
    r'|[@-Z\\-_]'                        # single-char: ESC @-Z, \, ]-_
    r'|\[[0-?]*[ -/]*[@-~]'              # CSI: ESC [ ... final
    r')'
)

_NOISE_RE = re.compile(
    r'^(?:'
    r'[✢✳✶✻✽·⏺⏵✦\s]*'           # 스피너 + Eave ✦ 문자들
    r'|[─═\-]{3,}'                 # 구분선 (--- 포함)
    r'|esc\s*to\s*interrupt'
    r'|\?\s*for\s*shortcuts'
    r'|❯\s*.*'
    r'|--\s*INSERT\s*--.*'
    r'|.*acceptedit.*'
    r'|.*shift\+tab.*'
    r'|\(✦\).*'
    r'|.*\bEave\b.*'
    r'|/\\\s*/\\'                  # /\ /\ (Eave 상단)
    r'|\(\(.*\)\)'                 # ((✦)(✦)) 등
    r'|\*[^*]+\*'                  # *ruffles feathers* 등
    r'|[-`.\u00b4]{1,4}'          # -, --, .., `´ 단독 잔재
    r'|\(.*><.*\)'                 # ( >< ) Eave 발
    r'|\.-\.'                      # .-. Eave 부리
    r'|[╭╮╰╯].*'                  # 말풍선 테두리
    r'|[│].*'                      # 말풍선 내용
    r')$',
    re.IGNORECASE
)

_STATUS_RE = re.compile(
    r'Elucidating|Actualizing|Actioning|Thinking|thinking with|'
    r'Musing|Pondering|Unravelling|Sautéed|Churned|Generating|'
    r'running stop hook|stop hook',
    re.IGNORECASE
)

_SPINNER_CHARS = re.compile(r'[✢✳✶✻✽⏺✦]')


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
                open(self.cfg.output_log, 'w').close()
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

    def capture_screenshot(self) -> str:
        lines = self.capture_pane(scrollback=200)
        return '\n'.join(lines).strip()

    def _send_text_blocking(self, text: str):
        subprocess.run(['tmux', 'send-keys', '-t', self.active_session, '-l', text])
        subprocess.run(['tmux', 'send-keys', '-t', self.active_session, 'Enter'])

    async def send(self, text: str) -> tuple[int, str]:
        if _DANGEROUS_CTRL.search(text):
            raise ValueError("허용되지 않은 제어 문자입니다.")
        sent = text.strip()
        async with self.lock:
            await asyncio.to_thread(self.ensure_session)
            if not self._pipe_active:
                await asyncio.to_thread(self.start_pipe)
            log_offset = self._log_size()
            await asyncio.to_thread(self._send_text_blocking, text)
        return log_offset, sent

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

    async def wait_for_response(self, log_offset: int, sent_text: str) -> str:
        start = time.time()
        last_size = log_offset
        last_change = time.time()
        while True:
            await asyncio.sleep(self.cfg.poll_interval)
            size, tail = self._read_log_tail(log_offset)
            if tail:
                # ANSI 제거 후 ❯ 프롬프트 감지 → 응답 완료
                clean_tail = _ANSI_ESC.sub('', tail).replace('\r\n', '\n').replace('\r', '\n')
                if CLAUDE_PROMPT_RE.search(clean_tail):
                    await asyncio.sleep(0.1)
                    return self._extract_from_log(log_offset, sent_text)
            if size != last_size:
                last_size = size
                last_change = time.time()
            elif size > log_offset and (time.time() - last_change) > self.cfg.quiet_seconds:
                # quiet 구간 — Claude가 아직 thinking 중인지 확인
                lines = self.capture_pane(scrollback=10)
                recent = '\n'.join(lines[-5:])
                if _STATUS_RE.search(recent):
                    last_change = time.time()  # 아직 처리 중 → 타이머 리셋
                else:
                    return self._extract_from_log(log_offset, sent_text)
            if time.time() - start > self.cfg.max_wait_seconds:
                return self._extract_from_log(log_offset, sent_text) or "(응답 시간 초과)"

    def _strip_ansi_to_lines(self, raw: str) -> list[str]:
        """ANSI 제거 + CR 처리 후 줄 분리."""
        cleaned = _ANSI_ESC.sub('', raw)
        # CR+LF → LF, 나머지 CR → LF
        cleaned = cleaned.replace('\r\n', '\n').replace('\r', '\n')
        return cleaned.split('\n')

    def _find_response_start(self, all_lines: list[str], sent_text: str) -> int:
        """capture_pane 결과에서 ❯ sent_text 줄을 역방향 검색, 그 다음 줄부터 응답."""
        sent_stripped = sent_text.strip()[:30]  # 앞 30자만 비교 (word-wrap 대응)
        for i in range(len(all_lines) - 1, -1, -1):
            line = all_lines[i].strip()
            if line.startswith('❯'):
                after_prompt = line[1:].strip()
                if after_prompt and (
                    sent_stripped.startswith(after_prompt[:20])
                    or after_prompt[:20] in sent_stripped
                ):
                    return i + 1
        return max(0, len(all_lines) - 50)

    def _extract_from_log(self, log_offset: int, sent_text: str) -> str:
        """capture_pane 기반 응답 추출 (렌더링된 텍스트 → ANSI 없음)."""
        all_lines = self.capture_pane(scrollback=500)
        start_idx = self._find_response_start(all_lines, sent_text)
        return self._clean_lines(all_lines[start_idx:])

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

    def _read_log_tail(self, offset: int, tail_bytes: int = 2048) -> tuple[int, str]:
        """(total_size, tail_text) 반환 — offset 이후 마지막 tail_bytes만 읽음."""
        try:
            with open(self.cfg.output_log, 'rb') as f:
                f.seek(0, 2)
                size = f.tell()
                read_from = max(offset, size - tail_bytes)
                f.seek(read_from)
                return size, f.read().decode('utf-8', errors='replace')
        except FileNotFoundError:
            return offset, ""

"""
tmux session controller — owns the PTY, iTerm2 just displays via attach.

출력 추출 전략:
  - pipe-pane  : 완료 감지용 타이밍 로그만 사용 (raw bytes, escape codes 있음)
  - capture-pane: 렌더링된 화면 텍스트 추출 (escape codes 없음)
  - 앵커 방식  : 전송 전 마지막 의미있는 줄을 앵커로 기록,
                 응답 후 그 앵커 이후 줄만 추출 (줄 번호 방식보다 안정적)
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
    r'|❯\s*.*'          # 프롬프트 줄 전체
    r')$',
    re.IGNORECASE
)

_STATUS_RE = re.compile(
    r'Elucidating|Actualizing|Thinking|thinking with|running stop hook'
    r'|stop hook',
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

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

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

    def stop_pipe(self):
        subprocess.run(['tmux', 'pipe-pane', '-t', self.cfg.session_name])
        self._pipe_active = False

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
                    'name': parts[0],
                    'windows': parts[1],
                    'attached': parts[2] == '1'
                })
        return sessions

    # ------------------------------------------------------------------
    # capture-pane 헬퍼
    # ------------------------------------------------------------------

    def capture_pane(self, scrollback: int = 500) -> list[str]:
        """
        렌더링된 화면 텍스트 반환 (escape codes 없음).
        scrollback: 최근 N줄까지 포함
        """
        r = subprocess.run(
            ['tmux', 'capture-pane', '-t', self.cfg.session_name,
             '-p', '-S', f'-{scrollback}'],
            capture_output=True, text=True
        )
        return r.stdout.splitlines()

    def _capture_anchor(self) -> str:
        """
        전송 전 앵커: 현재 화면의 마지막 의미있는 줄.
        노이즈/프롬프트 줄은 제외하고 역방향으로 탐색.
        """
        lines = self.capture_pane(scrollback=100)
        for line in reversed(lines):
            s = line.strip()
            if s and not _NOISE_RE.match(s) and not _STATUS_RE.search(s):
                return s
        return "__START__"

    def capture_screenshot(self) -> str:
        """현재 화면 전체 텍스트 (/cap 커맨드용)."""
        lines = self.capture_pane(scrollback=200)
        return '\n'.join(lines).strip()

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    async def send(self, text: str) -> tuple[int, str]:
        """
        텍스트 전송.
        Returns: (log_offset, anchor) — anchor는 응답 추출 기준점
        """
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

    # ------------------------------------------------------------------
    # 응답 대기 + 추출
    # ------------------------------------------------------------------

    async def wait_for_response(self, log_offset: int, anchor: str) -> str:
        """
        Claude 응답 완료 대기 후 anchor 이후 내용 반환.
        완료 감지: pipe-pane 로그 안정화 + 프롬프트 패턴
        """
        start = time.time()
        last_size = log_offset
        last_change = time.time()

        while True:
            await asyncio.sleep(self.cfg.poll_interval)
            raw = self._read_log_from(log_offset)
            size = len(raw)

            # 1. 프롬프트 패턴
            if size > 0 and CLAUDE_PROMPT_RE.search(raw[-500:]):
                await asyncio.sleep(0.4)
                return self._extract_response(anchor)

            # 2. 안정화
            if size != last_size:
                last_size = size
                last_change = time.time()
            elif size > 0 and (time.time() - last_change) > self.cfg.quiet_seconds:
                return self._extract_response(anchor)

            # 3. 타임아웃
            if time.time() - start > self.cfg.max_wait_seconds:
                return self._extract_response(anchor) or "(응답 시간 초과)"

    def _extract_response(self, anchor: str) -> str:
        """
        capture-pane에서 anchor 이후 줄만 추출.
        anchor가 없으면 최근 50줄 fallback.
        """
        all_lines = self.capture_pane(scrollback=500)

        if anchor == "__START__":
            new_lines = all_lines
        else:
            # 앵커를 아래에서 위로 탐색 (가장 최근 위치)
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

        # 연속 빈 줄 압축
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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

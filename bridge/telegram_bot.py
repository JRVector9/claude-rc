"""
Telegram bot — receives messages, routes to tmux session, returns output.
"""
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from .tmux_session import TmuxSession

logger = logging.getLogger(__name__)

MAX_MSG_LEN = 4096

# 단축 키보드 (y/n/tab/방향키 제외)
SHORTCUT_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("1"), KeyboardButton("2"),
         KeyboardButton("3"), KeyboardButton("4")],
        [KeyboardButton("↵ Enter"), KeyboardButton("↑"), KeyboardButton("↓"), KeyboardButton("⎋ Esc")],
        [KeyboardButton("📺 /cap")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

# 버튼 → tmux send-keys 매핑
KEY_MAP = {
    "↵ Enter": "Enter",
    "↑":       "Up",
    "↓":       "Down",
    "⎋ Esc":   "Escape",
    "📺 /cap":  None,   # 별도 처리
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

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _is_allowed(self, update: Update) -> bool:
        return update.effective_chat.id in self.allowed_chat_ids

    async def _reject(self, update: Update):
        await update.message.reply_text("Unauthorized.")
        logger.warning("Rejected chat_id=%s", update.effective_chat.id)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update): return await self._reject(update)
        await update.message.reply_text(
            "claude-rc 연결됨.\n"
            "메시지를 보내면 Claude Code로 전달됩니다.",
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
                f"```\n{chunk}\n```",
                parse_mode="Markdown",
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

    # ------------------------------------------------------------------
    # Message → Claude or special key
    # ------------------------------------------------------------------

    async def _handle_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update): return await self._reject(update)

        text = update.message.text.strip()
        if not text:
            return

        # 📺 /cap 버튼
        if text == "📺 /cap":
            return await self._cmd_cap(update, ctx)

        # 특수 키 버튼 (Enter / Esc)
        if text in KEY_MAP:
            key = KEY_MAP[text]
            if key:
                await self.session.send_key(key)
                await update.message.reply_text(
                    f"[{text}] 전송됨", reply_markup=SHORTCUT_KEYBOARD
                )
            return

        # 숫자 1-4: 그대로 입력
        if text in ("1", "2", "3", "4"):
            await self.session.send_key(text)
            await update.message.reply_text(
                f"[{text}] 전송됨", reply_markup=SHORTCUT_KEYBOARD
            )
            return

        # 일반 텍스트 → Claude
        thinking_msg = await update.message.reply_text(
            "⏳", reply_markup=SHORTCUT_KEYBOARD
        )

        try:
            log_offset, lines_before = await self.session.send(text)
            response = await self.session.wait_for_response(log_offset, lines_before)
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
                f"```\n{chunk}\n```",
                parse_mode="Markdown",
                reply_markup=SHORTCUT_KEYBOARD,
            )


def _split(text: str, size: int) -> list[str]:
    return [text[i:i+size] for i in range(0, len(text), size)]

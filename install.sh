#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.user.claude-rc.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"

echo "=== claude-rc installer ==="

# 1. 의존성 확인
command -v tmux >/dev/null || { echo "ERROR: tmux not found. brew install tmux"; exit 1; }
command -v python3 >/dev/null || { echo "ERROR: python3 not found"; exit 1; }

# 2. venv 생성 및 패키지 설치
echo "Installing Python dependencies..."
python3 -m venv "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/pip" install -q -r "$PROJECT_DIR/requirements.txt"

# 3. config 확인
if grep -q "YOUR_BOT_TOKEN_HERE" "$PROJECT_DIR/config/config.yaml"; then
    echo ""
    echo "⚠️  config/config.yaml 설정 필요:"
    echo "   1. telegram.bot_token 을 실제 봇 토큰으로 변경"
    echo "   2. telegram.allowed_chat_ids 에 내 Telegram chat ID 추가"
    echo ""
    echo "봇 토큰: @BotFather 에서 생성"
    echo "chat ID: @userinfobot 에서 확인"
    echo ""
fi

# 4. LaunchAgent plist 생성
echo "Installing LaunchAgent: $PLIST_PATH"
cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.claude-rc</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PROJECT_DIR/.venv/bin/python3</string>
        <string>$PROJECT_DIR/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/logs/launchd-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/logs/launchd-stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF

echo ""
echo "=== 설치 완료 ==="
echo ""
echo "다음 단계:"
echo "  1. config/config.yaml 에 봇 토큰과 chat ID 입력"
echo "  2. tmux 세션 시작:  tmux new -s claude"
echo "  3. 세션에서 Claude 실행:  claude"
echo "  4. iTerm2에서 연결:  tmux attach -t claude"
echo ""
echo "브릿지 시작 (수동):  python3 main.py"
echo "브릿지 시작 (LaunchAgent):  launchctl load ~/Library/LaunchAgents/$PLIST_NAME"
echo "브릿지 중지:  launchctl unload ~/Library/LaunchAgents/$PLIST_NAME"

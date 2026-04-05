#!/bin/bash
# claude-rc 스킬을 Claude Code에 등록합니다.
# 사용법: curl -fsSL https://raw.githubusercontent.com/YOUR_ID/claude-rc/main/install-skill.sh | bash

set -e

SKILL_DIR="$HOME/.claude/skills/telegram-rc"
REPO_RAW="https://raw.githubusercontent.com/YOUR_ID/claude-rc/main"

echo "=== claude-rc 스킬 설치 ==="

mkdir -p "$SKILL_DIR"

# GitHub에서 SKILL.md 직접 다운로드
if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$REPO_RAW/.claude/skills/telegram-rc/SKILL.md" -o "$SKILL_DIR/SKILL.md"
elif command -v wget >/dev/null 2>&1; then
    wget -q "$REPO_RAW/.claude/skills/telegram-rc/SKILL.md" -O "$SKILL_DIR/SKILL.md"
else
    echo "ERROR: curl 또는 wget이 필요합니다."
    exit 1
fi

echo ""
echo "✅ telegram-rc 스킬 설치 완료!"
echo ""
echo "Claude Code를 열고 /telegram-rc 를 입력하세요."
echo "봇 토큰과 Chat ID만 준비하면 자동으로 설치됩니다."

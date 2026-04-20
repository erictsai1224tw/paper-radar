#!/usr/bin/env bash
# 一次性初始化腳本：新 project clone 下來後執行一次
# 用法: ./bootstrap.sh [project-name]
set -euo pipefail

# Resolve real script path (follow symlinks) — portable POSIX-ish (no readlink -f)
_resolve_script_path() {
    local src="$1"
    while [ -L "$src" ]; do
        local dir
        dir="$(cd -P -- "$(dirname -- "$src")" && pwd)"
        src="$(readlink -- "$src")"
        case "$src" in
            /*) ;;                      # absolute, use as-is
            *)  src="$dir/$src" ;;      # relative, prepend dir
        esac
    done
    printf '%s' "$src"
}

SCRIPT_PATH="$(_resolve_script_path "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd -P -- "$(dirname -- "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

PROJECT_NAME="${1:-}"
if [[ -z "$PROJECT_NAME" ]]; then
    read -rp "Project name: " PROJECT_NAME
fi

if [[ -z "$PROJECT_NAME" ]]; then
    echo "ERROR: project name is required" >&2
    exit 1
fi

# Git identity（可用 env 傳入，否則 prompt）— 只寫到 local repo，不碰 global
if [[ -z "${GIT_NAME:-}" ]]; then
    read -rp "Git user.name (僅此專案 local): " GIT_NAME
fi
if [[ -z "${GIT_EMAIL:-}" ]]; then
    read -rp "Git user.email (僅此專案 local): " GIT_EMAIL
fi
if [[ -z "$GIT_NAME" || -z "$GIT_EMAIL" ]]; then
    echo "ERROR: git name / email 不能為空" >&2
    exit 1
fi

echo "🚀 Bootstrapping project: $PROJECT_NAME"

# 1. 重置 git history（並設定 local identity，不碰 global）
rm -rf .git
git init -b main > /dev/null
git config user.name "$GIT_NAME"
git config user.email "$GIT_EMAIL"

# 2. 用 child-project 骨架覆寫 README.md（原本描述 template 本身）
cat > README.md <<EOF
# $PROJECT_NAME

TODO: 一段話描述你的專案。

## Quick Start

\`\`\`bash
make build && make up && make terminal
\`\`\`

進 container 後：

\`\`\`bash
source /venv/bin/activate
uv sync --active
\`\`\`

## Docs
- [CLAUDE.md](./CLAUDE.md) — coding conventions、architecture、git workflow
EOF
echo "  ✔ rewrote README.md"

# 3. 替換 PROJECT_NAME_PLACEHOLDER（escape sed replacement metachars: \ & /）
ESCAPED_NAME=$(printf '%s' "$PROJECT_NAME" | sed -e 's/[\\/&]/\\&/g')
FILES_TO_PATCH=(
    "pyproject.toml"
    ".devcontainer/devcontainer.json"
    "CLAUDE.md"
)
for f in "${FILES_TO_PATCH[@]}"; do
    if [[ -f "$f" ]] && grep -q "PROJECT_NAME_PLACEHOLDER" "$f"; then
        sed -i.bak "s/PROJECT_NAME_PLACEHOLDER/${ESCAPED_NAME}/g" "$f"
        rm -f "${f}.bak"
        echo "  ✔ patched $f"
    fi
done

# 4. 建立 .env（把 GIT_NAME / GIT_EMAIL 直接填進去，container 內會沿用同一組 identity）
if [[ ! -f .env ]]; then
    cp .env.example .env
fi
ESCAPED_NAME_ENV=$(printf '%s' "$GIT_NAME"  | sed -e 's/[\\/&]/\\&/g')
ESCAPED_EMAIL_ENV=$(printf '%s' "$GIT_EMAIL" | sed -e 's/[\\/&]/\\&/g')
sed -i.bak "s/^GIT_NAME=.*/GIT_NAME=${ESCAPED_NAME_ENV}/"   .env
sed -i.bak "s/^GIT_EMAIL=.*/GIT_EMAIL=${ESCAPED_EMAIL_ENV}/" .env
rm -f .env.bak
echo "  ✔ wrote .env with GIT_NAME / GIT_EMAIL"

# 4. Initial commit
git add .
git commit -m "chore: bootstrap $PROJECT_NAME from template" > /dev/null

# 5. Self-delete (the resolved real script, not a symlink)
rm -- "$SCRIPT_PATH"

echo ""
echo "✅ Bootstrap 完成！"
echo ""
echo "下一步: make build && make up && make terminal"

# ==========================================
# 通用 ML 開發環境：CUDA 12.4 + uv + Node + AI CLI tools + pytorch
# ==========================================
FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

# 1. 安裝 uv (Python 套件管理工具)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 2. 環境變數
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=3.12 \
    VIRTUAL_ENV=/venv \
    UV_PROJECT_ENVIRONMENT=/venv \
    HF_HOME=/cache/huggingface \
    PYTHONPATH=/app:$PYTHONPATH \
    PATH="/home/docker/.npm-global/bin:/home/docker/.claude/local/bin:/venv/bin:/home/docker/.local/bin:$PATH"

# 3. 安裝系統依賴 + ML 常用動態函式庫 + Node.js 22
RUN apt-get update && apt-get install -y \
    software-properties-common \
    git \
    curl \
    wget \
    build-essential \
    ca-certificates \
    pkg-config \
    vim \
    tmux \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# 3b. supercronic — rootless cron for scheduled agents
RUN curl -fsSL -o /usr/local/bin/supercronic \
      https://github.com/aptible/supercronic/releases/download/v0.2.33/supercronic-linux-amd64 \
    && chmod +x /usr/local/bin/supercronic

# 4. 安裝 GitHub CLI
RUN mkdir -p -m 755 /etc/apt/keyrings \
    && out=$(mktemp) && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    && cat $out | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && mkdir -p -m 755 /etc/apt/sources.list.d \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# 5. 建立使用者與目錄
RUN groupadd -g 1000 docker && \
    useradd -u 1000 -g 1000 -m -s /bin/bash docker && \
    mkdir -p /app /venv /cache/huggingface /home/docker/.npm-global && \
    chown -R docker:docker /app /venv /cache /home/docker

WORKDIR /app
USER docker

# 6. 安裝 Python 依賴骨架（uv）
COPY --chown=docker:docker pyproject.toml ./
RUN uv venv $VIRTUAL_ENV && \
    uv sync --active --no-cache --no-install-project

# 7. 複製 project
COPY --chown=docker:docker . .

# 8. 安裝 AI CLI tools
RUN curl -fsSL https://claude.ai/install.sh | bash && \
    npm config set prefix '/home/docker/.npm-global' && \
    npm cache clean --force && \
    npm install -g @google/gemini-cli @github/copilot

# 9. Git / SSH 基礎設定
RUN mkdir -p /home/docker/.ssh && \
    chmod 700 /home/docker/.ssh && \
    git config --global --add safe.directory /app

COPY --chown=docker:docker docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["sleep", "infinity"]

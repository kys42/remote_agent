# Remote Agent System

텔레그램을 통해 Claude Code, Gemini CLI 등 다양한 AI 에이전트를 원격으로 실행할 수 있는 브릿지 시스템입니다.

## 🏗️ 아키텍처

```
[Telegram] ↔ [Telegram Bridge] ↔ [Agent Server] ↔ [AI Agents]
                                                    ├── Claude Code
                                                    ├── Gemini CLI
                                                    └── Custom Agents
```

## 🚀 주요 기능

- **다중 에이전트 지원**: Claude Code, Gemini CLI 및 커스텀 에이전트
- **세션 관리**: 사용자별 독립적인 세션
- **실시간 스트리밍**: 에이전트 출력을 실시간으로 전송
- **유연한 구조**: 새로운 에이전트를 쉽게 추가 가능
- **텔레그램 인터페이스**: 편리한 채팅 기반 상호작용

## 📦 설치

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 환경 설정

`.env` 파일을 생성하고 다음 내용을 설정하세요:

```env
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# Server Configuration
BRIDGE_PORT=8000
EXECUTOR_PORT=8001
WEBSOCKET_PORT=8002

# Claude Code Configuration
CLAUDE_CODE_PATH=claude
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Session Configuration
SESSION_TIMEOUT=3600
MAX_SESSIONS=10
```

### 3. 텔레그램 봇 생성

1. [@BotFather](https://t.me/botfather)에게 `/newbot` 명령으로 새 봇 생성
2. 봇 토큰을 `.env` 파일의 `TELEGRAM_BOT_TOKEN`에 설정

## 🎯 사용법

### 시스템 실행

```bash
# 전체 시스템 실행 (기본)
python main.py

# 에이전트 서버만 실행
python main.py --mode server

# 텔레그램 브릿지만 실행
python main.py --mode bridge
```

### 텔레그램 봇 명령어

- `/start` - 봇 시작 및 기본 세션 생성
- `/help` - 도움말 보기
- `/agents` - 사용 가능한 에이전트 목록
- `/new [에이전트] [디렉토리]` - 새 세션 시작
- `/switch [에이전트]` - 에이전트 변경
- `/status` - 현재 세션 상태 확인
- `/end` - 현재 세션 종료

### 사용 예시

```
# Claude Code로 세션 시작
/new claude_code /home/user/project

# 작업 요청
README 파일을 작성해줘

# Gemini CLI로 변경
/switch gemini_cli

# 다른 작업 요청
이 코드를 최적화해줘
```

## 🔧 에이전트 추가

### 1. 기본 제공 에이전트

- **Claude Code**: `claude_code`
- **Gemini CLI**: `gemini_cli` (경로 설정 필요)

### 2. 커스텀 에이전트 추가

`src/agent_system.py`에서 새로운 에이전트 클래스를 만들거나, API를 통해 런타임에 등록할 수 있습니다:

```python
from src.agent_system import CustomAgent, AgentConfig, AgentType

# 커스텀 에이전트 설정
config = AgentConfig(
    agent_type=AgentType.CUSTOM,
    executable_path="/path/to/your/agent",
    default_args=["--format", "json"],
    max_sessions=5
)

# 명령 템플릿 정의
command_template = "{executable} --prompt {message} --stream"
custom_agent = CustomAgent(config, command_template)
```

## 🔌 API 엔드포인트

Agent Server는 다음 REST API를 제공합니다:

- `GET /agents` - 사용 가능한 에이전트 목록
- `POST /sessions` - 새 세션 생성
- `GET /sessions/{session_id}` - 세션 정보 조회
- `DELETE /sessions/{session_id}` - 세션 종료
- `POST /execute` - 명령 실행 (스트리밍)
- `WS /ws/{session_id}` - WebSocket 연결

## 🏃‍♂️ 개발 모드

개발 중에는 각 컴포넌트를 별도로 실행할 수 있습니다:

```bash
# Agent Server 실행
python src/agent_server.py

# Telegram Bridge 실행
python src/telegram_bridge.py
```

## 📁 프로젝트 구조

```
remote_agent/
├── src/
│   ├── agent_system.py      # 에이전트 시스템 기본 클래스
│   ├── agent_server.py      # FastAPI 기반 에이전트 서버
│   └── telegram_bridge.py   # 텔레그램 봇 브릿지
├── main.py                  # 메인 실행 파일
├── requirements.txt         # Python 의존성
├── .env.example            # 환경 변수 예시
└── README.md               # 이 문서
```

## 🛠️ 문제 해결

### 일반적인 문제들

1. **봇이 응답하지 않음**
   - `TELEGRAM_BOT_TOKEN`이 올바른지 확인
   - 봇이 차단되지 않았는지 확인

2. **Claude Code 실행 실패**
   - `claude` 명령이 PATH에 있는지 확인
   - `ANTHROPIC_API_KEY`가 설정되었는지 확인

3. **세션 생성 실패**
   - Agent Server가 실행 중인지 확인
   - 포트 충돌이 없는지 확인

### 로그 확인

시스템 실행 시 상세한 로그가 출력됩니다. 문제 발생 시 로그를 확인하여 원인을 파악할 수 있습니다.

## 🤝 기여

이 프로젝트에 기여하고 싶으시다면:

1. Fork하여 새 브랜치 생성
2. 변경사항 구현
3. 테스트 실행
4. Pull Request 생성

## 📄 라이선스

MIT License

## 📞 지원

문제가 있거나 제안사항이 있으시면 Issue를 생성해주세요.
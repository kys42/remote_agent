### 프로젝트 개요

*   **목적**: 텔레그램을 통해 Claude Code, Gemini CLI 등 다양한 AI 에이전트를 원격으로 실행하는 브릿지 시스템.
*   **아키텍처**: `[Telegram] ↔ [Telegram Bridge] ↔ [Agent Server] ↔ [AI Agents]`
*   **주요 기술**:
    *   **Python**: `FastAPI` (Agent Server), `python-telegram-bot` (Telegram Bridge), `asyncio` (비동기 처리)
    *   **Node.js**: 보조적인 역할 또는 초기 버전의 잔재로 추정.

### 핵심 구성 요소

1.  **`agent_system.py`**
    *   `BaseAgent` 추상 클래스를 통해 다양한 AI 에이전트를 표준화.
    *   `AgentManager`가 세션과 에이전트를 중앙에서 관리.
    *   세션별로 독립적인 프로세스를 생성하여 명령을 실행.

2.  **`agent_server.py`**
    *   `FastAPI`를 사용하여 `AgentManager`의 기능을 RESTful API 및 WebSocket으로 노출.
    *   외부 컴포넌트(주로 Telegram Bridge)가 에이전트를 제어할 수 있도록 함.

3.  **`telegram_bridge.py`**
    *   텔레그램 봇의 인터페이스 역할.
    *   사용자 명령을 파싱하여 `agent_server`의 API를 호출.
    *   `ALLOWED_USER_IDS` 환경 변수를 통한 접근 제어 기능 포함.

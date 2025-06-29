from fastapi import FastAPI, WebSocket, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import asyncio
import json
import logging
import os
from dotenv import load_dotenv

from agent_system import (
    AgentManager, AgentType, AgentConfig, 
    ClaudeCodeAgent, GeminiCLIAgent, CustomAgent
)
from persistent_claude_agent import PersistentClaudeAgent
from pty_claude_agent import PTYClaudeAgent
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import config

load_dotenv()

logger = logging.getLogger(__name__)

# Pydantic 모델들
class CreateSessionRequest(BaseModel):
    agent_type: str
    user_id: str
    working_directory: Optional[str] = None

class ExecuteCommandRequest(BaseModel):
    session_id: str
    message: str

class RegisterAgentRequest(BaseModel):
    agent_type: str
    executable_path: str
    default_args: List[str] = []
    working_directory: Optional[str] = None
    timeout: int = 3600
    max_sessions: int = 5
    stream_format: str = "stream-json"

class AgentServer:
    def __init__(self):
        self.agent_manager = AgentManager()
        self._setup_default_agents()
    
    def _setup_default_agents(self):
        """기본 에이전트들 설정"""
        # Claude Code 에이전트 (지속적인 세션)
        claude_config = AgentConfig(
            agent_type=AgentType.CLAUDE_CODE,
            executable_path=os.getenv('CLAUDE_CODE_PATH', 'claude'),
            default_args=[],
            timeout=int(os.getenv('SESSION_TIMEOUT', 3600)),
            max_sessions=int(os.getenv('MAX_SESSIONS', 10)),
            stream_format='stream-json'
        )
        claude_agent = PTYClaudeAgent(claude_config)
        self.agent_manager.register_agent(AgentType.CLAUDE_CODE, claude_agent)
        
        # Gemini CLI 에이전트 (예시 - 실제 경로는 환경에 따라 다름)
        gemini_path = os.getenv('GEMINI_CLI_PATH')
        if gemini_path and os.path.exists(gemini_path):
            gemini_config = AgentConfig(
                agent_type=AgentType.GEMINI_CLI,
                executable_path=gemini_path,
                default_args=['--format', 'json'],
                timeout=3600,
                max_sessions=5,
                stream_format='json'
            )
            gemini_agent = GeminiCLIAgent(gemini_config)
            self.agent_manager.register_agent(AgentType.GEMINI_CLI, gemini_agent)

# FastAPI 앱 설정
app = FastAPI(title="Agent Server API", version="1.0.0")
server = AgentServer()

@app.get("/")
async def root():
    return {"message": "Agent Server is running", "version": "1.0.0"}

@app.get("/agents")
async def list_agents():
    """사용 가능한 에이전트 목록"""
    return {
        "agents": server.agent_manager.get_available_agents(),
        "total": len(server.agent_manager.agents)
    }

@app.post("/agents/register")
async def register_custom_agent(request: RegisterAgentRequest):
    """커스텀 에이전트 등록"""
    try:
        # AgentType.CUSTOM으로 새 에이전트 생성
        config = AgentConfig(
            agent_type=AgentType.CUSTOM,
            executable_path=request.executable_path,
            default_args=request.default_args,
            working_directory=request.working_directory,
            timeout=request.timeout,
            max_sessions=request.max_sessions,
            stream_format=request.stream_format
        )
        
        # 커스텀 에이전트 생성 (기본 템플릿 사용)
        command_template = "{executable} {message}"
        if request.default_args:
            command_template = "{executable} " + " ".join(request.default_args) + " {message}"
        
        custom_agent = CustomAgent(config, command_template)
        
        # 에이전트 타입을 동적으로 생성 (에이전트 이름 기반)
        agent_name = f"custom_{request.agent_type}"
        custom_agent_type = AgentType(agent_name) if hasattr(AgentType, agent_name) else AgentType.CUSTOM
        
        server.agent_manager.register_agent(custom_agent_type, custom_agent)
        
        return {
            "message": f"Custom agent '{request.agent_type}' registered successfully",
            "agent_type": agent_name
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/sessions")
async def create_session(request: CreateSessionRequest):
    """새 세션 생성"""
    try:
        # 문자열을 AgentType으로 변환
        agent_type = None
        for at in AgentType:
            if at.value == request.agent_type:
                agent_type = at
                break
        
        if agent_type is None:
            raise HTTPException(status_code=400, detail=f"Unknown agent type: {request.agent_type}")
        
        session_id = await server.agent_manager.create_session(
            agent_type=agent_type,
            user_id=request.user_id,
            working_directory=request.working_directory
        )
        
        if session_id is None:
            raise HTTPException(status_code=500, detail="Failed to create session")
        
        return {"session_id": session_id}
    
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/sessions/{session_id}")
async def terminate_session(session_id: str):
    """세션 종료"""
    success = await server.agent_manager.terminate_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"message": "Session terminated successfully"}

@app.get("/sessions/{session_id}")
async def get_session_info(session_id: str):
    """세션 정보 조회"""
    info = await server.agent_manager.get_session_info(session_id)
    if not info:
        raise HTTPException(status_code=404, detail="Session not found")
    return info

@app.get("/sessions")
async def list_sessions(user_id: Optional[str] = None):
    """세션 목록 조회"""
    return await server.agent_manager.list_all_sessions(user_id)

@app.post("/execute")
async def execute_command(request: ExecuteCommandRequest):
    """명령 실행 (스트리밍)"""
    async def generate():
        try:
            async for output in server.agent_manager.execute_command(request.session_id, request.message):
                yield f"data: {json.dumps(output)}\n\n"
        except Exception as e:
            logger.error(f"Error in execute_command: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket 엔드포인트"""
    await websocket.accept()
    
    try:
        while True:
            # 클라이언트로부터 메시지 받기
            data = await websocket.receive_text()
            
            try:
                message_data = json.loads(data)
                message = message_data.get("message", "")
                
                if not message:
                    await websocket.send_text(json.dumps({"error": "Empty message"}))
                    continue
                
                # 명령 실행 및 결과 스트리밍
                async for output in server.agent_manager.execute_command(session_id, message):
                    await websocket.send_text(json.dumps(output))
                    
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"error": "Invalid JSON format"}))
            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}")
                await websocket.send_text(json.dumps({"error": str(e)}))
                
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await websocket.close()

@app.get("/health")
async def health_check():
    """헬스 체크"""
    return {
        "status": "healthy",
        "agents": len(server.agent_manager.agents),
        "total_sessions": sum([
            len(agent.sessions) for agent in server.agent_manager.agents.values()
        ])
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv('EXECUTOR_PORT', 8001))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
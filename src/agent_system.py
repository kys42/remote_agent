from abc import ABC, abstractmethod
import asyncio
import subprocess
import json
import uuid
import logging
import time
from typing import Dict, Optional, AsyncGenerator, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import os
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import config

logger = logging.getLogger(__name__)

class AgentType(Enum):
    CLAUDE_CODE = "claude_code"
    GEMINI_CLI = "gemini_cli"
    CUSTOM = "custom"

@dataclass
class AgentConfig:
    """에이전트 설정"""
    agent_type: AgentType
    executable_path: str
    default_args: List[str]
    working_directory: Optional[str] = None
    timeout: int = 3600
    max_sessions: int = 5
    stream_format: str = "stream-json"  # 출력 형식

@dataclass
class Session:
    """세션 정보"""
    id: str
    user_id: str
    agent_type: AgentType
    process: Optional[subprocess.Popen]
    created_at: datetime
    working_directory: str
    config: AgentConfig

class BaseAgent(ABC):
    """에이전트 기본 클래스"""
    
    def __init__(self, config: AgentConfig):
        self.config = config
        self.sessions: Dict[str, Session] = {}
    
    @abstractmethod
    async def prepare_command(self, message: str, session: Session) -> List[str]:
        """실행할 명령어 준비"""
        pass
    
    @abstractmethod
    async def parse_output(self, output: str) -> Dict[str, Any]:
        """출력 파싱"""
        pass
    
    async def create_session(self, user_id: str, working_directory: str = None) -> str:
        """새로운 세션 생성"""
        session_id = str(uuid.uuid4())
        
        # 세션 수 제한 확인
        user_sessions = [s for s in self.sessions.values() if s.user_id == user_id]
        if len(user_sessions) >= self.config.max_sessions:
            # 가장 오래된 세션 제거
            oldest_session = min(user_sessions, key=lambda s: s.created_at)
            await self.terminate_session(oldest_session.id)
        
        if working_directory is None:
            working_directory = self.config.working_directory or os.getcwd()
        
        session = Session(
            id=session_id,
            user_id=user_id,
            agent_type=self.config.agent_type,
            process=None,
            created_at=datetime.now(),
            working_directory=working_directory,
            config=self.config
        )
        
        self.sessions[session_id] = session
        logger.info(f"Session created: {session_id} for user {user_id} with agent {self.config.agent_type.value}")
        return session_id
    
    async def execute_command(self, session_id: str, message: str) -> AsyncGenerator[Dict[str, Any], None]:
        """명령 실행 및 스트리밍 출력"""
        if session_id not in self.sessions:
            yield {"error": "Session not found", "session_id": session_id}
            return
        
        session = self.sessions[session_id]
        
        try:
            # 명령어 준비
            cmd = await self.prepare_command(message, session)
            
            # subprocess 실행 (서브클래스의 create_process 사용)
            if hasattr(self, 'create_process'):
                process = await self.create_process(cmd, session)
            else:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=session.working_directory
                )
            
            session.process = process
            
            # 실시간 출력 스트리밍 (타임아웃 적용)
            logger.info(f"Starting output streaming for session {session_id}")
            start_time = time.time()
            timeout = 300  # 5분 타임아웃
            
            while True:
                try:
                    # 타임아웃 체크
                    if time.time() - start_time > timeout:
                        logger.warning(f"Session {session_id} timed out after {timeout} seconds")
                        process.terminate()
                        yield {
                            "error": f"Command timed out after {timeout} seconds",
                            "session_id": session_id,
                            "agent_type": session.agent_type.value,
                            "timeout": True
                        }
                        break
                    
                    # 0.1초 타임아웃으로 readline 시도
                    line = await asyncio.wait_for(process.stdout.readline(), timeout=0.1)
                    if not line:
                        logger.info(f"Session {session_id}: No more output, breaking loop")
                        break
                    
                    output = line.decode('utf-8').strip()
                    if output:
                        logger.debug(f"Session {session_id} output: {output[:100]}...")
                        # 전체 출력을 로그에 출력 (디버깅용)
                        logger.debug(f"Session {session_id} full output: {output}")
                        parsed_output = await self.parse_output(output)
                        parsed_output["session_id"] = session_id
                        parsed_output["agent_type"] = session.agent_type.value
                        
                        # 에러가 포함된 출력인지 확인
                        if parsed_output.get("is_error") or parsed_output.get("error"):
                            logger.error(f"Session {session_id} received error output: {parsed_output}")
                        
                        yield parsed_output
                        
                except asyncio.TimeoutError:
                    # readline 타임아웃 - 프로세스가 아직 실행 중인지 확인
                    if process.returncode is not None:
                        logger.info(f"Session {session_id}: Process finished during timeout")
                        break
                    continue
                except UnicodeDecodeError as e:
                    logger.warning(f"Session {session_id}: Unicode decode error: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Session {session_id}: Unexpected error in output loop: {e}")
                    break
            
            # 프로세스 종료 대기
            await process.wait()
            
            # 에러가 있으면 처리
            if process.returncode != 0:
                stderr = await process.stderr.read()
                error_msg = stderr.decode('utf-8').strip()
                logger.error(f"Session {session_id} failed with return code {process.returncode}: {error_msg}")
                yield {
                    "error": f"Command failed: {error_msg}",
                    "session_id": session_id,
                    "agent_type": session.agent_type.value,
                    "return_code": process.returncode
                }
            else:
                logger.info(f"Session {session_id} completed successfully")
        
        except Exception as e:
            logger.error(f"Error executing command in session {session_id}: {e}", exc_info=True)
            yield {
                "error": str(e),
                "session_id": session_id,
                "agent_type": session.agent_type.value,
                "exception_type": type(e).__name__
            }
        finally:
            logger.info(f"Cleaning up session {session_id}")
            session.process = None
    
    async def terminate_session(self, session_id: str) -> bool:
        """세션 종료"""
        if session_id not in self.sessions:
            return False
        
        session = self.sessions[session_id]
        
        if session.process and session.process.returncode is None:
            try:
                session.process.terminate()
                await asyncio.sleep(0.1)
                if session.process.returncode is None:
                    session.process.kill()
            except Exception as e:
                logger.error(f"Error terminating process for session {session_id}: {e}")
        
        del self.sessions[session_id]
        logger.info(f"Session terminated: {session_id}")
        return True
    
    async def get_session_info(self, session_id: str) -> Optional[Dict]:
        """세션 정보 조회"""
        if session_id not in self.sessions:
            return None
        
        session = self.sessions[session_id]
        return {
            "id": session.id,
            "user_id": session.user_id,
            "agent_type": session.agent_type.value,
            "created_at": session.created_at.isoformat(),
            "working_directory": session.working_directory,
            "is_running": session.process is not None and session.process.returncode is None
        }
    
    async def list_sessions(self, user_id: str = None) -> Dict:
        """세션 목록 조회"""
        sessions = []
        for session in self.sessions.values():
            if user_id is None or session.user_id == user_id:
                info = await self.get_session_info(session.id)
                if info:
                    sessions.append(info)
        
        return {
            "sessions": sessions,
            "total": len(sessions),
            "max_sessions": self.config.max_sessions,
            "agent_type": self.config.agent_type.value
        }

class ClaudeCodeAgent(BaseAgent):
    """Claude Code 에이전트"""
    
    async def prepare_command(self, message: str, session: Session) -> List[str]:
        """Claude Code 명령어 준비"""
        return [
            self.config.executable_path,
            '--print',
            '--output-format=stream-json',
            '--verbose',
            message
        ]
    
    async def create_process(self, command: List[str], session: Session) -> subprocess.Popen:
        """프로세스 생성 (환경변수 설정 포함)"""
        env = os.environ.copy()
        # Claude 설정 디렉토리 지정
        env['HOME'] = os.path.expanduser('~')
        
        return await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=session.working_directory,
            env=env
        )
    
    async def parse_output(self, output: str) -> Dict[str, Any]:
        """Claude Code 출력 파싱"""
        try:
            # JSON 형식 파싱 시도
            parsed = json.loads(output)
            # Claude Code의 실제 출력 내용 추출
            if "type" in parsed and parsed["type"] == "assistant":
                content = ""
                if "message" in parsed and "content" in parsed["message"]:
                    for content_item in parsed["message"]["content"]:
                        if content_item.get("type") == "text":
                            content += content_item.get("text", "")
                return {
                    "type": "assistant_response",
                    "content": content,
                    "raw": parsed,
                    "timestamp": datetime.now().isoformat()
                }
            elif "type" in parsed and parsed["type"] == "result":
                return {
                    "type": "result",
                    "content": parsed.get("result", ""),
                    "raw": parsed,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "type": "raw_json",
                    "content": str(parsed),
                    "raw": parsed,
                    "timestamp": datetime.now().isoformat()
                }
        except json.JSONDecodeError:
            # 일반 텍스트로 처리
            return {
                "type": "text",
                "content": output,
                "timestamp": datetime.now().isoformat()
            }

class GeminiCLIAgent(BaseAgent):
    """Gemini CLI 에이전트 (예시)"""
    
    async def prepare_command(self, message: str, session: Session) -> List[str]:
        """Gemini CLI 명령어 준비"""
        return [
            self.config.executable_path,
            '--prompt', message,
            '--stream'
        ] + self.config.default_args
    
    async def parse_output(self, output: str) -> Dict[str, Any]:
        """Gemini CLI 출력 파싱"""
        try:
            # Gemini CLI의 출력 형식에 맞게 파싱
            return json.loads(output)
        except json.JSONDecodeError:
            return {
                "type": "text",
                "content": output,
                "timestamp": datetime.now().isoformat()
            }

class CustomAgent(BaseAgent):
    """커스텀 에이전트"""
    
    def __init__(self, config: AgentConfig, command_template: str, parser_func=None):
        super().__init__(config)
        self.command_template = command_template
        self.parser_func = parser_func or self._default_parser
    
    async def prepare_command(self, message: str, session: Session) -> List[str]:
        """커스텀 에이전트 명령어 준비"""
        # 템플릿에서 {message} 치환
        cmd_str = self.command_template.format(
            executable=self.config.executable_path,
            message=message
        )
        return cmd_str.split()
    
    async def parse_output(self, output: str) -> Dict[str, Any]:
        """커스텀 파서 사용"""
        return await self.parser_func(output)
    
    async def _default_parser(self, output: str) -> Dict[str, Any]:
        """기본 파서"""
        return {
            "type": "text",
            "content": output,
            "timestamp": datetime.now().isoformat()
        }

class AgentManager:
    """에이전트 관리자"""
    
    def __init__(self):
        self.agents: Dict[AgentType, BaseAgent] = {}
        self.session_to_agent: Dict[str, AgentType] = {}
    
    def register_agent(self, agent_type: AgentType, agent: BaseAgent):
        """에이전트 등록"""
        self.agents[agent_type] = agent
        logger.info(f"Agent registered: {agent_type.value}")
    
    def get_available_agents(self) -> List[str]:
        """사용 가능한 에이전트 목록"""
        return [agent_type.value for agent_type in self.agents.keys()]
    
    async def create_session(self, agent_type: AgentType, user_id: str, working_directory: str = None) -> Optional[str]:
        """지정된 에이전트로 세션 생성"""
        if agent_type not in self.agents:
            logger.error(f"Agent not found: {agent_type.value}")
            return None
        
        agent = self.agents[agent_type]
        session_id = await agent.create_session(user_id, working_directory)
        
        if session_id:
            self.session_to_agent[session_id] = agent_type
        
        return session_id
    
    async def execute_command(self, session_id: str, message: str) -> AsyncGenerator[Dict[str, Any], None]:
        """세션에서 명령 실행"""
        if session_id not in self.session_to_agent:
            yield {"error": "Session not found", "session_id": session_id}
            return
        
        agent_type = self.session_to_agent[session_id]
        agent = self.agents[agent_type]
        
        async for result in agent.execute_command(session_id, message):
            yield result
    
    async def terminate_session(self, session_id: str) -> bool:
        """세션 종료"""
        if session_id not in self.session_to_agent:
            return False
        
        agent_type = self.session_to_agent[session_id]
        agent = self.agents[agent_type]
        
        success = await agent.terminate_session(session_id)
        
        if success and session_id in self.session_to_agent:
            del self.session_to_agent[session_id]
        
        return success
    
    async def get_session_info(self, session_id: str) -> Optional[Dict]:
        """세션 정보 조회"""
        if session_id not in self.session_to_agent:
            return None
        
        agent_type = self.session_to_agent[session_id]
        agent = self.agents[agent_type]
        
        return await agent.get_session_info(session_id)
    
    async def list_all_sessions(self, user_id: str = None) -> Dict:
        """모든 에이전트의 세션 목록"""
        all_sessions = []
        total_sessions = 0
        
        for agent_type, agent in self.agents.items():
            agent_sessions = await agent.list_sessions(user_id)
            all_sessions.extend(agent_sessions["sessions"])
            total_sessions += agent_sessions["total"]
        
        return {
            "sessions": all_sessions,
            "total": total_sessions,
            "available_agents": self.get_available_agents()
        }
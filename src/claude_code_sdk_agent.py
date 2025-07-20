import asyncio
import logging
import json
import uuid
from typing import Dict, Optional, AsyncGenerator, Any, List
from dataclasses import dataclass
from datetime import datetime
import os

try:
    import anyio
    from claude_code_sdk import (
        query, 
        ClaudeCodeOptions, 
        AssistantMessage, 
        UserMessage,
        SystemMessage,
        ResultMessage,
        TextBlock, 
        ToolUseBlock, 
        ToolResultBlock,
        ClaudeSDKError,
        CLINotFoundError,
        CLIConnectionError,
        ProcessError,
        CLIJSONDecodeError
    )
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False

from agent_system import BaseAgent, AgentType, AgentConfig, Session

logger = logging.getLogger(__name__)

class ClaudeCodeSDKAgent(BaseAgent):
    """공식 Claude Code SDK를 사용하는 에이전트 클래스
    
    이 에이전트는 Anthropic의 공식 Claude Code SDK를 사용하여
    Claude와 대화하고 코드 작업을 수행합니다.
    
    주요 기능:
    - 비동기 메시지 스트리밍 처리
    - 다양한 도구 (Read, Write, Edit, Bash 등) 지원
    - 세션별 대화 기록 관리
    - 상세한 에러 처리 및 로깅
    """
    
    def __init__(self, config: AgentConfig):
        if not SDK_AVAILABLE:
            raise ImportError("claude-code-sdk is not installed. Install with: pip install claude-code-sdk")
        
        super().__init__(config)
        # 대화 기록을 저장하는 딕셔너리 (세션 ID -> 메시지 리스트)
        self.conversation_history: Dict[str, List] = {}
        
        # SDK 옵션 설정
        self.sdk_options = ClaudeCodeOptions(
            max_turns=int(os.getenv('CLAUDE_MAX_TURNS', 10)),
            system_prompt=os.getenv('CLAUDE_SYSTEM_PROMPT', "You are a helpful coding assistant."),
            permission_mode=os.getenv('CLAUDE_PERMISSION_MODE', 'acceptEdits'),
            allowed_tools=self._get_allowed_tools()
        )
    
    def _get_allowed_tools(self) -> List[str]:
        """환경변수에서 허용된 도구 목록을 가져와 반환
        
        Returns:
            List[str]: 허용된 도구 이름 리스트
        """
        tools_env = os.getenv('CLAUDE_ALLOWED_TOOLS', '')
        if tools_env:
            return [tool.strip() for tool in tools_env.split(',')]
        # 기본 허용 도구들
        return ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
    
    async def prepare_command(self, message: str, session: Session) -> List[str]:
        """메시지를 명령어 형태로 변환 (호환성을 위해 유지)
        
        Claude Code SDK는 CLI 기반이 아닌 직접 API 호출 방식이므로
        사용자 메시지를 그대로 반환합니다.
        
        Args:
            message (str): 사용자 입력 메시지
            session (Session): 현재 세션 객체
            
        Returns:
            List[str]: 메시지를 포함한 리스트
        """
        return [message]
    
    async def create_session(self, user_id: str, working_directory: str = None) -> str:
        """새로운 Claude SDK 세션을 생성
        
        Args:
            user_id (str): 사용자 식별자
            working_directory (str, optional): 작업 디렉토리 경로
            
        Returns:
            str: 생성된 세션 ID
        """
        session_id = await super().create_session(user_id, working_directory)
        
        # 대화 기록 초기화
        self.conversation_history[session_id] = []
        
        logger.info(f"Claude SDK session created: {session_id} in {working_directory}")
        return session_id
    
    async def execute_command(self, session_id: str, message: str) -> AsyncGenerator[Dict[str, Any], None]:
        """주어진 메시지를 Claude Code SDK로 전송하고 응답을 스트리밍으로 처리
        
        Args:
            session_id (str): 세션 식별자
            message (str): Claude에게 전송할 메시지
            
        Yields:
            Dict[str, Any]: 파싱된 응답 데이터
        """
        if session_id not in self.sessions:
            yield {"error": "Session not found", "session_id": session_id}
            return
        
        session = self.sessions[session_id]
        
        try:
            # SDK 옵션에 작업 디렉토리 설정
            options = ClaudeCodeOptions(
                max_turns=self.sdk_options.max_turns,
                system_prompt=self.sdk_options.system_prompt,
                cwd=session.working_directory,
                permission_mode=self.sdk_options.permission_mode,
                allowed_tools=self.sdk_options.allowed_tools
            )
            
            logger.info(f"Executing Claude SDK query in session {session_id}: {message[:100]}...")
            
            # 시작 메시지 전송
            yield {
                "type": "status",
                "content": "Claude Code SDK 실행 중...",
                "session_id": session_id,
                "agent_type": "claude_code",
                "timestamp": datetime.now().isoformat()
            }
            
            # SDK를 통한 쿼리 실행
            messages_received = []
            
            try:
                async for sdk_message in query(prompt=message, options=options):
                    messages_received.append(sdk_message)
                    
                    # 메시지 파싱 및 전송
                    parsed_output = await self.parse_sdk_message(sdk_message)
                    parsed_output["session_id"] = session_id
                    parsed_output["agent_type"] = "claude_code"
                    
                    yield parsed_output
                
                # 대화 기록에 저장
                self.conversation_history[session_id].extend(messages_received)
                
                # 완료 메시지
                yield {
                    "type": "completion",
                    "content": f"Claude Code SDK 실행 완료. {len(messages_received)}개 메시지 수신",
                    "session_id": session_id,
                    "agent_type": "claude_code",
                    "timestamp": datetime.now().isoformat(),
                    "message_count": len(messages_received)
                }
            
            # SDK 특정 에러 타입들을 개별적으로 처리
            except CLINotFoundError:
                error_msg = "Claude Code CLI가 설치되지 않았습니다. 'npm install -g @anthropic-ai/claude-code'로 설치해주세요."
                logger.error(f"CLI not found in session {session_id}")
                yield {
                    "error": error_msg,
                    "error_type": "cli_not_found",
                    "session_id": session_id,
                    "agent_type": "claude_code",
                    "timestamp": datetime.now().isoformat()
                }
            
            except CLIConnectionError as e:
                error_msg = f"Claude Code CLI 연결 오류: {str(e)}"
                logger.error(f"CLI connection error in session {session_id}: {e}")
                yield {
                    "error": error_msg,
                    "error_type": "cli_connection_error",
                    "session_id": session_id,
                    "agent_type": "claude_code",
                    "timestamp": datetime.now().isoformat()
                }
            
            except ProcessError as e:
                error_msg = f"Claude Code 프로세스 오류 (exit code: {e.exit_code}): {str(e)}"
                logger.error(f"Process error in session {session_id}: {e}")
                yield {
                    "error": error_msg,
                    "error_type": "process_error",
                    "exit_code": e.exit_code,
                    "session_id": session_id,
                    "agent_type": "claude_code",
                    "timestamp": datetime.now().isoformat()
                }
            
            except CLIJSONDecodeError as e:
                error_msg = f"Claude Code 응답 파싱 오류: {str(e)}"
                logger.error(f"JSON decode error in session {session_id}: {e}")
                yield {
                    "error": error_msg,
                    "error_type": "json_decode_error",
                    "session_id": session_id,
                    "agent_type": "claude_code",
                    "timestamp": datetime.now().isoformat()
                }
            
            except ClaudeSDKError as e:
                error_msg = f"Claude SDK 일반 오류: {str(e)}"
                logger.error(f"Claude SDK error in session {session_id}: {e}")
                yield {
                    "error": error_msg,
                    "error_type": "claude_sdk_error",
                    "session_id": session_id,
                    "agent_type": "claude_code",
                    "timestamp": datetime.now().isoformat()
                }
            
            except Exception as sdk_error:
                error_msg = f"예상치 못한 오류: {str(sdk_error)}"
                logger.error(f"Unexpected error in session {session_id}: {sdk_error}", exc_info=True)
                yield {
                    "error": error_msg,
                    "error_type": "unexpected_error",
                    "session_id": session_id,
                    "agent_type": "claude_code",
                    "timestamp": datetime.now().isoformat()
                }
        
        except Exception as e:
            logger.error(f"Error in Claude SDK agent session {session_id}: {e}", exc_info=True)
            yield {
                "error": f"Claude SDK Agent 오류: {str(e)}",
                "error_type": "agent_error",
                "session_id": session_id,
                "agent_type": "claude_code",
                "timestamp": datetime.now().isoformat()
            }
    
    def _safe_serialize(self, obj) -> Any:
        """객체를 JSON 직렬화 가능한 형태로 변환"""
        if obj is None:
            return None
        elif isinstance(obj, (str, int, float, bool)):
            return obj
        elif isinstance(obj, dict):
            return {k: self._safe_serialize(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._safe_serialize(item) for item in obj]
        elif hasattr(obj, '__dict__'):
            return self._safe_serialize(obj.__dict__)
        else:
            return str(obj)
    
    def _extract_content_from_blocks(self, content_blocks) -> Dict[str, Any]:
        """공식 SDK의 콘텐츠 블록들에서 데이터를 추출
        
        Args:
            content_blocks: AssistantMessage의 content 블록 리스트
            
        Returns:
            Dict[str, Any]: 추출된 콘텐츠 정보
        """
        extracted_data = {
            "text_content": [],
            "tool_uses": [],
            "tool_results": [],
            "raw_blocks": []
        }
        
        if not content_blocks:
            return extracted_data
            
        for block in content_blocks:
            # 원본 블록 정보 저장
            extracted_data["raw_blocks"].append(self._safe_serialize(block))
            
            # TextBlock 처리
            if isinstance(block, TextBlock):
                extracted_data["text_content"].append(block.text)
            
            # ToolUseBlock 처리
            elif isinstance(block, ToolUseBlock):
                tool_info = {
                    "id": getattr(block, 'id', None),
                    "name": getattr(block, 'name', None),
                    "input": getattr(block, 'input', None)
                }
                extracted_data["tool_uses"].append(tool_info)
            
            # ToolResultBlock 처리
            elif isinstance(block, ToolResultBlock):
                result_info = {
                    "tool_use_id": getattr(block, 'tool_use_id', None),
                    "content": getattr(block, 'content', None),
                    "is_error": getattr(block, 'is_error', False)
                }
                extracted_data["tool_results"].append(result_info)
            
            # 기타 블록 타입에 대해서는 문자열로 변환
            else:
                extracted_data["text_content"].append(str(block))
        
        return extracted_data

    async def parse_sdk_message(self, message) -> Dict[str, Any]:
        """공식 Claude SDK 메시지를 파싱하여 구조화된 데이터로 변환
        
        Args:
            message: Claude SDK에서 수신한 메시지 객체
            
        Returns:
            Dict[str, Any]: 파싱된 메시지 데이터
        """
        try:
            # 메시지 타입 확인
            message_type = type(message).__name__
            
            # AssistantMessage 처리
            if isinstance(message, AssistantMessage):
                extracted_data = self._extract_content_from_blocks(message.content)
                
                return {
                    "type": "assistant_message",
                    "content": "\n".join(extracted_data["text_content"]) if extracted_data["text_content"] else "",
                    "text_blocks": extracted_data["text_content"],
                    "tool_uses": extracted_data["tool_uses"],
                    "tool_results": extracted_data["tool_results"],
                    "block_count": len(extracted_data["raw_blocks"]),
                    "raw_blocks": extracted_data["raw_blocks"],
                    "timestamp": datetime.now().isoformat()
                }
            
            # UserMessage 처리
            elif isinstance(message, UserMessage):
                content = ""
                if hasattr(message, 'content'):
                    if isinstance(message.content, str):
                        content = message.content
                    else:
                        content = str(message.content)
                
                return {
                    "type": "user_message",
                    "content": content,
                    "timestamp": datetime.now().isoformat()
                }
            
            # SystemMessage 처리
            elif isinstance(message, SystemMessage):
                content = getattr(message, 'content', str(message))
                return {
                    "type": "system_message",
                    "content": str(content),
                    "timestamp": datetime.now().isoformat()
                }
            
            # ResultMessage 처리
            elif isinstance(message, ResultMessage):
                return {
                    "type": "result_message",
                    "content": str(message),
                    "raw_data": self._safe_serialize(message),
                    "timestamp": datetime.now().isoformat()
                }
            
            # 알려지지 않은 메시지 타입 처리
            else:
                logger.warning(f"Unknown message type: {message_type}")
                return {
                    "type": f"unknown_{message_type.lower()}",
                    "content": str(message),
                    "raw_data": self._safe_serialize(message),
                    "timestamp": datetime.now().isoformat()
                }
                
        except Exception as e:
            logger.error(f"Error parsing SDK message: {e}", exc_info=True)
            return {
                "type": "parse_error",
                "content": str(message),
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    async def parse_output(self, output: str) -> Dict[str, Any]:
        """기존 메서드와의 호환성을 위한 구현"""
        return {
            "type": "text",
            "content": output,
            "timestamp": datetime.now().isoformat()
        }
    
    async def terminate_session(self, session_id: str) -> bool:
        """세션을 종료하고 관련 리소스를 정리
        
        Args:
            session_id (str): 종료할 세션 ID
            
        Returns:
            bool: 종료 성공 여부
        """
        # 대화 기록 정리
        if session_id in self.conversation_history:
            conversation_length = len(self.conversation_history[session_id])
            del self.conversation_history[session_id]
            logger.info(f"Cleaned up conversation history for session {session_id} ({conversation_length} messages)")
        
        return await super().terminate_session(session_id)
    
    async def get_conversation_history(self, session_id: str) -> Optional[List]:
        """세션의 대화 기록을 조회
        
        Args:
            session_id (str): 세션 ID
            
        Returns:
            Optional[List]: 대화 기록 리스트 또는 None
        """
        return self.conversation_history.get(session_id)
    
    async def get_session_info(self, session_id: str) -> Optional[Dict]:
        """세션의 상세 정보를 조회 (대화 기록 및 SDK 옵션 포함)
        
        Args:
            session_id (str): 세션 ID
            
        Returns:
            Optional[Dict]: 세션 정보 또는 None
        """
        info = await super().get_session_info(session_id)
        if info and session_id in self.conversation_history:
            info["conversation_length"] = len(self.conversation_history[session_id])
            info["sdk_options"] = {
                "max_turns": self.sdk_options.max_turns,
                "permission_mode": self.sdk_options.permission_mode,
                "allowed_tools": self.sdk_options.allowed_tools,
                "system_prompt": self.sdk_options.system_prompt[:100] + "..." if len(self.sdk_options.system_prompt) > 100 else self.sdk_options.system_prompt
            }
        return info
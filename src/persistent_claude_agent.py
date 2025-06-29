import asyncio
import json
import logging
from typing import Dict, Any, AsyncGenerator, Optional
from agent_system import BaseAgent, Session

logger = logging.getLogger(__name__)

class PersistentClaudeAgent(BaseAgent):
    """지속적인 Claude Code 에이전트 (Interactive 모드)"""
    
    def __init__(self, config):
        super().__init__(config)
        self.claude_processes: Dict[str, asyncio.subprocess.Process] = {}
        self.executing_sessions: set = set()  # 실행 중인 세션 추적
    
    async def create_session(self, user_id: str, working_directory: str = None) -> str:
        """세션 생성 및 Claude interactive 프로세스 시작"""
        session_id = await super().create_session(user_id, working_directory)
        
        # Claude interactive 프로세스 시작
        try:
            process = await asyncio.create_subprocess_exec(
                self.config.executable_path,
                '--print',
                '--output-format=stream-json',
                '--verbose',
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_directory or ".",
                env=self._get_environment()
            )
            
            self.claude_processes[session_id] = process
            logger.info(f"Started persistent Claude process for session {session_id}")
            
            # 초기화 메시지 읽기 및 검증
            init_success = await self._read_initial_output(process)
            if not init_success:
                # stderr에서 에러 메시지 확인
                try:
                    stderr_output = await asyncio.wait_for(process.stderr.read(), timeout=1.0)
                    error_msg = stderr_output.decode('utf-8').strip()
                    logger.error(f"Claude stderr: {error_msg}")
                except:
                    logger.error("Could not read Claude stderr")
                
                process.terminate()
                raise Exception("Claude initialization failed - no system init message received")
            
        except Exception as e:
            logger.error(f"Failed to start Claude process for session {session_id}: {e}")
            if session_id in self.sessions:
                del self.sessions[session_id]
            raise
        
        return session_id
    
    def _get_environment(self) -> Dict[str, str]:
        """환경변수 설정"""
        import os
        env = os.environ.copy()
        env['HOME'] = os.path.expanduser('~')
        return env
    
    async def _read_initial_output(self, process):
        """초기화 출력 읽기 (system init 메시지 필수)"""
        try:
            # system init 메시지 대기 (필수)
            line = await asyncio.wait_for(process.stdout.readline(), timeout=10.0)
            if line:
                output = line.decode('utf-8').strip()
                logger.info(f"Claude initialized: {output}")
                return True
            else:
                logger.error("Claude process started but no init message received")
                return False
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for Claude initialization - process may have failed")
            return False
    
    
    async def execute_command(self, session_id: str, message: str) -> AsyncGenerator[Dict[str, Any], None]:
        """지속적인 세션에서 명령 실행"""
        if session_id not in self.sessions:
            yield {"error": "Session not found", "session_id": session_id}
            return
        
        if session_id not in self.claude_processes:
            yield {"error": "Claude process not found", "session_id": session_id}
            return
        
        # 중복 실행 방지
        if session_id in self.executing_sessions:
            yield {"error": "Session is already executing a command", "session_id": session_id}
            return
        
        self.executing_sessions.add(session_id)
        
        process = self.claude_processes[session_id]
        session = self.sessions[session_id]
        
        try:
            # 메시지를 Claude 프로세스에 전송
            input_data = message + '\n'
            process.stdin.write(input_data.encode('utf-8'))
            await process.stdin.drain()
            
            logger.info(f"Sent message to Claude session {session_id}: {message[:50]}...")
            
            # 응답 스트리밍
            async for output in self._stream_output(process, session_id):
                output["session_id"] = session_id
                output["agent_type"] = self.config.agent_type.value
                yield output
                
        except Exception as e:
            logger.error(f"Error in persistent session {session_id}: {e}")
            yield {
                "error": str(e),
                "session_id": session_id,
                "agent_type": self.config.agent_type.value
            }
        finally:
            # 실행 완료 후 세션에서 제거
            self.executing_sessions.discard(session_id)
    
    async def _stream_output(self, process, session_id) -> AsyncGenerator[Dict[str, Any], None]:
        """Claude 출력 스트리밍"""
        consecutive_timeouts = 0
        max_consecutive_timeouts = 3  # 3번 연속 타임아웃이면 종료
        
        while True:
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=2.0)
                consecutive_timeouts = 0  # 성공하면 리셋
                
                if not line:
                    # 프로세스가 종료되었거나 더 이상 출력이 없음
                    if process.returncode is not None:
                        logger.warning(f"Claude process ended for session {session_id}")
                        break
                    # 빈 줄이면 계속 대기
                    continue
            
            except asyncio.TimeoutError:
                consecutive_timeouts += 1
                logger.debug(f"Stream timeout {consecutive_timeouts}/{max_consecutive_timeouts} for session {session_id}")
                
                if consecutive_timeouts >= max_consecutive_timeouts:
                    logger.info(f"Stream ended after {consecutive_timeouts} consecutive timeouts for session {session_id}")
                    break
                continue
            
            output = line.decode('utf-8').strip()
            if output:
                logger.debug(f"Claude output: {output[:100]}...")
                
                try:
                    parsed = json.loads(output)
                    
                    # 결과 타입에 따라 처리
                    if parsed.get("type") == "result":
                        yield {
                            "type": "result",
                            "content": parsed.get("result", ""),
                            "is_error": parsed.get("is_error", False),
                            "raw": parsed
                        }
                        break  # 결과가 나오면 이 턴 종료
                    elif parsed.get("type") == "assistant":
                        # 어시스턴트 응답 처리
                        content = ""
                        if "message" in parsed and "content" in parsed["message"]:
                            for item in parsed["message"]["content"]:
                                if item.get("type") == "text":
                                    content += item.get("text", "")
                        
                        yield {
                            "type": "assistant_response",
                            "content": content,
                            "raw": parsed
                        }
                    else:
                        # 기타 시스템 메시지
                        yield {
                            "type": "raw_json",
                            "content": output,
                            "raw": parsed
                        }
                        
                except json.JSONDecodeError:
                    # JSON이 아닌 일반 텍스트
                    yield {
                        "type": "text",
                        "content": output
                    }
    
    async def terminate_session(self, session_id: str) -> bool:
        """세션 및 Claude 프로세스 종료"""
        success = await super().terminate_session(session_id)
        
        if session_id in self.claude_processes:
            try:
                process = self.claude_processes[session_id]
                process.stdin.close()
                process.terminate()
                await asyncio.sleep(0.1)
                if process.returncode is None:
                    process.kill()
                del self.claude_processes[session_id]
                logger.info(f"Terminated Claude process for session {session_id}")
            except Exception as e:
                logger.error(f"Error terminating Claude process: {e}")
        
        return success
    
    async def prepare_command(self, message: str, session: Session) -> list:
        """이 클래스에서는 사용하지 않음 (interactive 모드)"""
        return []
    
    async def parse_output(self, output: str) -> Dict[str, Any]:
        """이 클래스에서는 사용하지 않음 (직접 파싱)"""
        return {"content": output}
import asyncio
import pty
import os
import select
import termios
import logging
import json
from typing import Dict, Any, AsyncGenerator, Optional
from agent_system import BaseAgent, Session

logger = logging.getLogger(__name__)

class PTYClaudeAgent(BaseAgent):
    """PTY(pseudo-terminal)를 사용한 Claude 에이전트"""
    
    def __init__(self, config):
        super().__init__(config)
        self.pty_sessions: Dict[str, Dict] = {}  # session_id -> {master_fd, pid, buffer}
    
    async def create_session(self, user_id: str, working_directory: str = None) -> str:
        """PTY 세션 생성"""
        session_id = await super().create_session(user_id, working_directory)
        
        try:
            # PTY 마스터/슬레이브 쌍 생성
            master_fd, slave_fd = pty.openpty()
            
            # Claude 프로세스를 PTY 슬레이브에서 실행
            pid = os.fork()
            
            if pid == 0:  # 자식 프로세스
                # 슬레이브를 표준 입출력으로 설정
                os.close(master_fd)
                os.dup2(slave_fd, 0)  # stdin
                os.dup2(slave_fd, 1)  # stdout 
                os.dup2(slave_fd, 2)  # stderr
                os.close(slave_fd)
                
                # 작업 디렉토리 변경
                if working_directory:
                    os.chdir(working_directory)
                
                # 환경변수 설정
                env = os.environ.copy()
                env['HOME'] = os.path.expanduser('~')
                env['TERM'] = 'xterm-256color'
                
                # Claude를 --print 모드로 실행
                claude_cmd = f'{self.config.executable_path} --print --output-format=stream-json --verbose'
                os.execve(
                    '/bin/bash',
                    ['bash', '-c', claude_cmd],
                    env
                )
            else:  # 부모 프로세스
                os.close(slave_fd)
                
                # 논블로킹 모드 설정
                os.set_blocking(master_fd, False)
                
                # 세션 정보 저장
                self.pty_sessions[session_id] = {
                    'master_fd': master_fd,
                    'pid': pid,
                    'buffer': b'',
                    'working_directory': working_directory or os.getcwd()
                }
                
                logger.info(f"Started PTY Claude session {session_id} with PID {pid}")
                
                # 초기화 대기 (Claude 시작 메시지)
                await self._wait_for_initialization(session_id)
                
        except Exception as e:
            logger.error(f"Failed to create PTY session {session_id}: {e}")
            if session_id in self.sessions:
                del self.sessions[session_id]
            raise
        
        return session_id
    
    async def _wait_for_initialization(self, session_id: str, timeout: float = 10.0):
        """Claude 초기화 대기"""
        pty_info = self.pty_sessions[session_id]
        master_fd = pty_info['master_fd']
        
        start_time = asyncio.get_event_loop().time()
        buffer = b''
        
        while True:
            # 타임아웃 체크
            if asyncio.get_event_loop().time() - start_time > timeout:
                logger.warning(f"Claude initialization timeout for session {session_id}")
                break
            
            # 데이터 읽기 시도
            try:
                ready, _, _ = select.select([master_fd], [], [], 0.1)
                if ready:
                    data = os.read(master_fd, 1024)
                    if data:
                        buffer += data
                        text = buffer.decode('utf-8', errors='ignore')
                        
                        # Claude 프롬프트나 초기화 메시지 확인
                        if '>' in text or 'Claude' in text or len(buffer) > 100:
                            logger.info(f"Claude initialized for session {session_id}")
                            pty_info['buffer'] = buffer
                            break
                else:
                    await asyncio.sleep(0.1)
            except (OSError, UnicodeDecodeError):
                await asyncio.sleep(0.1)
    
    async def execute_command(self, session_id: str, message: str) -> AsyncGenerator[Dict[str, Any], None]:
        """PTY 세션에서 명령 실행"""
        if session_id not in self.sessions or session_id not in self.pty_sessions:
            yield {"error": "Session not found", "session_id": session_id}
            return
        
        pty_info = self.pty_sessions[session_id]
        master_fd = pty_info['master_fd']
        
        try:
            # 명령 전송
            command = message + '\n'
            os.write(master_fd, command.encode('utf-8'))
            logger.info(f"Sent command to PTY session {session_id}: {message[:50]}...")
            
            # 응답 스트리밍
            async for output in self._stream_pty_output(session_id):
                output["session_id"] = session_id
                output["agent_type"] = self.config.agent_type.value
                yield output
                
        except Exception as e:
            logger.error(f"Error executing command in PTY session {session_id}: {e}")
            yield {
                "error": str(e),
                "session_id": session_id,
                "agent_type": self.config.agent_type.value
            }
    
    async def _stream_pty_output(self, session_id: str) -> AsyncGenerator[Dict[str, Any], None]:
        """PTY 출력 스트리밍"""
        pty_info = self.pty_sessions[session_id]
        master_fd = pty_info['master_fd']
        
        buffer = b''
        consecutive_empty_reads = 0
        max_empty_reads = 50  # 5초 (0.1초 * 50)
        
        try:
            while consecutive_empty_reads < max_empty_reads:
                try:
                    # select를 사용해서 데이터 대기
                    ready, _, _ = select.select([master_fd], [], [], 0.1)
                    
                    if ready:
                        data = os.read(master_fd, 1024)
                        if data:
                            consecutive_empty_reads = 0
                            buffer += data
                            
                            # 라인별로 처리
                            while b'\n' in buffer:
                                line, buffer = buffer.split(b'\n', 1)
                                text = line.decode('utf-8', errors='ignore').strip()
                                
                                if text:
                                    # 일반 텍스트 출력
                                    yield {
                                        "type": "text",
                                        "content": text,
                                        "timestamp": asyncio.get_event_loop().time()
                                    }
                        else:
                            consecutive_empty_reads += 1
                    else:
                        consecutive_empty_reads += 1
                        await asyncio.sleep(0.1)
                        
                except OSError as e:
                    if e.errno == 5:  # Input/output error (process terminated)
                        logger.info(f"PTY process terminated for session {session_id}")
                        break
                    else:
                        logger.error(f"PTY read error: {e}")
                        break
            
            # 남은 버퍼 내용 출력
            if buffer:
                text = buffer.decode('utf-8', errors='ignore').strip()
                if text:
                    yield {
                        "type": "text", 
                        "content": text,
                        "timestamp": asyncio.get_event_loop().time()
                    }
                    
        except Exception as e:
            logger.error(f"Error streaming PTY output: {e}")
            yield {"error": f"Stream error: {str(e)}"}
    
    async def terminate_session(self, session_id: str) -> bool:
        """PTY 세션 종료"""
        success = await super().terminate_session(session_id)
        
        if session_id in self.pty_sessions:
            try:
                pty_info = self.pty_sessions[session_id]
                master_fd = pty_info['master_fd']
                pid = pty_info['pid']
                
                # 프로세스 종료
                try:
                    os.kill(pid, 15)  # SIGTERM
                    await asyncio.sleep(0.5)
                    os.kill(pid, 9)   # SIGKILL (강제 종료)
                except ProcessLookupError:
                    pass  # 이미 종료됨
                
                # 파일 디스크립터 닫기
                os.close(master_fd)
                
                del self.pty_sessions[session_id]
                logger.info(f"Terminated PTY session {session_id}")
                
            except Exception as e:
                logger.error(f"Error terminating PTY session {session_id}: {e}")
        
        return success
    
    async def prepare_command(self, message: str, session: Session) -> list:
        """PTY에서는 사용하지 않음"""
        return []
    
    async def parse_output(self, output: str) -> Dict[str, Any]:
        """PTY에서는 사용하지 않음"""
        return {"content": output}
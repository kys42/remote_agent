"""
Claude Code CLI 기반 에이전트
-p (print mode)와 --continue, --resume 옵션을 활용한 간단한 구현
"""

import asyncio
import subprocess
import logging
import json
import uuid
import os
from typing import Dict, Any, AsyncGenerator, Optional, List
from dataclasses import dataclass
from datetime import datetime

from agent_system import BaseAgent, AgentType, AgentConfig, Session

logger = logging.getLogger(__name__)

@dataclass
class ClaudeCLISession:
    """Claude CLI 세션 정보"""
    session_id: str
    claude_session_id: Optional[str] = None  # Claude 자체 세션 ID
    working_directory: str = "."
    conversation_turns: int = 0
    last_command: Optional[str] = None

class ClaudeCodeCLIAgent(BaseAgent):
    """Claude Code CLI를 사용하는 간단한 에이전트
    
    주요 특징:
    - subprocess를 사용해 claude 명령어 실행
    - -p (print mode)로 비대화형 실행
    - --continue로 대화 연속성 유지
    - --resume으로 특정 세션 재개
    """
    
    def __init__(self, config: AgentConfig):
        super().__init__(config)
        self.cli_sessions: Dict[str, ClaudeCLISession] = {}
        
        # Claude 실행 파일 경로 확인
        self.claude_path = self._find_claude_executable()
        if not self.claude_path:
            raise FileNotFoundError("Claude Code CLI not found. Install with: npm install -g @anthropic-ai/claude-code")
    
    def _find_claude_executable(self) -> Optional[str]:
        """Claude 실행 파일 경로 찾기"""
        # 환경변수에서 지정된 경로 확인
        if hasattr(self.config, 'executable_path') and self.config.executable_path:
            if os.path.isfile(self.config.executable_path):
                return self.config.executable_path
        
        # 기본 경로들 확인
        possible_paths = [
            'claude',
            '/usr/local/bin/claude',
            '/usr/bin/claude',
            os.path.expanduser('~/.npm-global/bin/claude')
        ]
        
        for path in possible_paths:
            try:
                result = subprocess.run([path, '--version'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    return path
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue
        
        return None
    
    async def create_session(self, user_id: str, working_directory: str = None) -> str:
        """새로운 CLI 세션 생성"""
        session_id = await super().create_session(user_id, working_directory)
        
        # CLI 세션 정보 저장
        self.cli_sessions[session_id] = ClaudeCLISession(
            session_id=session_id,
            working_directory=working_directory or os.getcwd()
        )
        
        logger.info(f"Created Claude CLI session {session_id} in {working_directory}")
        return session_id
    
    async def execute_command(self, session_id: str, message: str) -> AsyncGenerator[Dict[str, Any], None]:
        """메시지를 Claude CLI로 실행"""
        if session_id not in self.sessions or session_id not in self.cli_sessions:
            yield {"error": "Session not found", "session_id": session_id}
            return
        
        cli_session = self.cli_sessions[session_id]
        session = self.sessions[session_id]
        
        try:
            # 명령어 구성
            cmd = await self._build_claude_command(cli_session, message)
            
            # 시작 상태 전송
            yield {
                "type": "status",
                "content": f"Claude CLI 실행 중... (명령: {' '.join(cmd[:3])}...)",
                "session_id": session_id,
                "agent_type": "claude_cli",
                "timestamp": datetime.now().isoformat()
            }
            
            # Claude CLI 실행
            async for result in self._execute_claude_cli(cmd, cli_session):
                result["session_id"] = session_id
                result["agent_type"] = "claude_cli"
                yield result
            
            # 세션 정보 업데이트
            cli_session.conversation_turns += 1
            cli_session.last_command = message
            
        except Exception as e:
            logger.error(f"Error executing command in session {session_id}: {e}")
            yield {
                "error": f"Claude CLI 실행 오류: {str(e)}",
                "error_type": "cli_execution_error",
                "session_id": session_id,
                "agent_type": "claude_cli",
                "timestamp": datetime.now().isoformat()
            }
    
    async def _build_claude_command(self, cli_session: ClaudeCLISession, message: str) -> List[str]:
        """Claude CLI 명령어 구성"""
        cmd = [self.claude_path]
        
        # 기본 옵션
        cmd.extend(['-p'])  # print mode
        
        # 출력 형식 (JSON이면 파싱하기 쉬움)
        if self.config.stream_format == 'json':
            cmd.extend(['--output-format', 'json'])
        
        # 세션 연속성
        if cli_session.conversation_turns > 0:
            if cli_session.claude_session_id:
                # 특정 세션으로 재개
                cmd.extend(['--resume', cli_session.claude_session_id])
            else:
                # 가장 최근 대화 계속
                cmd.extend(['--continue'])
        
        # 작업 디렉토리 설정
        if cli_session.working_directory != os.getcwd():
            cmd.extend(['--cwd', cli_session.working_directory])
        
        # 메시지 추가
        cmd.append(message)
        
        return cmd
    
    async def _execute_claude_cli(self, cmd: List[str], cli_session: ClaudeCLISession) -> AsyncGenerator[Dict[str, Any], None]:
        """Claude CLI 프로세스 실행 및 출력 스트리밍"""
        try:
            # 환경변수 설정 (Claude 인증 정보를 위해)
            env = os.environ.copy()
            env['HOME'] = os.path.expanduser('~')
            
            # 잘못된 API 키 플레이스홀더 제거
            if env.get('ANTHROPIC_API_KEY') in ['your_anthropic_api_key_here', 'your_key_here', '']:
                del env['ANTHROPIC_API_KEY']
                logger.info("Removed placeholder ANTHROPIC_API_KEY, will use browser auth")
            
            # 추가 환경변수들
            if 'XDG_CONFIG_HOME' not in env:
                env['XDG_CONFIG_HOME'] = os.path.join(env['HOME'], '.config')
            if 'XDG_CACHE_HOME' not in env:
                env['XDG_CACHE_HOME'] = os.path.join(env['HOME'], '.cache')
            
            logger.info(f"Starting Claude CLI with HOME={env['HOME']}")
            
            # 프로세스 시작
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cli_session.working_directory,
                env=env
            )
            
            logger.info(f"Started Claude CLI process: {' '.join(cmd)}")
            
            # 실시간 스트림 읽기
            async for output in self._stream_realtime(process.stdout, process.stderr, cli_session):
                yield output
            
            # 프로세스 완료 대기
            return_code = await process.wait()
            
            # 에러 코드에 따른 처리
            if return_code == 1:
                # API 키 에러일 가능성 높음
                yield {
                    "error": "Claude CLI 실행 실패. API 키를 확인해주세요.",
                    "error_type": "api_key_error",
                    "return_code": return_code,
                    "help": "해결방법: claude auth set-key YOUR_ANTHROPIC_API_KEY",
                    "timestamp": datetime.now().isoformat()
                }
            elif return_code != 0:
                # 기타 에러
                yield {
                    "error": f"Claude CLI가 에러로 종료되었습니다 (exit code: {return_code})",
                    "error_type": "cli_exit_error",
                    "return_code": return_code,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                # 정상 완료
                yield {
                    "type": "completion",
                    "content": f"Claude CLI 실행 완료 (exit code: {return_code})",
                    "return_code": return_code,
                    "timestamp": datetime.now().isoformat()
                }
            
        except Exception as e:
            logger.error(f"Error running Claude CLI: {e}")
            yield {
                "error": f"CLI 프로세스 오류: {str(e)}",
                "error_type": "process_error",
                "timestamp": datetime.now().isoformat()
            }
    
    async def _stream_realtime(self, stdout, stderr, cli_session: ClaudeCLISession) -> AsyncGenerator[Dict[str, Any], None]:
        """실시간으로 stdout과 stderr 스트리밍"""
        
        # 간단한 방법: stdout만 먼저 처리해보기
        try:
            while True:
                # stdout 읽기
                stdout_line = await asyncio.wait_for(stdout.readline(), timeout=0.1)
                if not stdout_line:
                    break
                    
                text = stdout_line.decode('utf-8', errors='ignore').strip()
                if text:
                    # Claude 세션 ID 추출 시도
                    if 'session_id' in text.lower() or 'session:' in text.lower():
                        session_id = self._extract_claude_session_id(text)
                        if session_id:
                            cli_session.claude_session_id = session_id
                    
                    yield {
                        "type": "text",
                        "stream_type": "stdout",
                        "content": text,
                        "timestamp": datetime.now().isoformat()
                    }
                
        except asyncio.TimeoutError:
            # 타임아웃은 정상적인 종료 조건
            pass
        except Exception as e:
            yield {
                "type": "error",
                "content": f"스트림 읽기 오류: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
        
        # stderr도 확인
        try:
            while True:
                stderr_line = await asyncio.wait_for(stderr.readline(), timeout=0.1)
                if not stderr_line:
                    break
                    
                text = stderr_line.decode('utf-8', errors='ignore').strip()
                if text:
                    yield {
                        "type": "error",
                        "stream_type": "stderr",
                        "content": text,
                        "timestamp": datetime.now().isoformat()
                    }
                    
        except asyncio.TimeoutError:
            # 타임아웃은 정상적인 종료 조건
            pass
        except Exception as e:
            yield {
                "type": "error",
                "content": f"stderr 읽기 오류: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
    
    
    def _extract_claude_session_id(self, text: str) -> Optional[str]:
        """텍스트에서 Claude 세션 ID 추출"""
        import re
        
        # UUID 패턴 찾기
        uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
        matches = re.findall(uuid_pattern, text, re.IGNORECASE)
        
        if matches:
            return matches[0]
        
        return None
    
    async def prepare_command(self, message: str, session: Session) -> List[str]:
        """호환성을 위한 메서드 (실제로는 사용하지 않음)"""
        return [message]
    
    async def parse_output(self, output: str) -> Dict[str, Any]:
        """출력 파싱 (JSON 형식 지원)"""
        try:
            # JSON 파싱 시도
            if output.strip().startswith('{') and output.strip().endswith('}'):
                return json.loads(output)
        except json.JSONDecodeError:
            pass
        
        # 일반 텍스트
        return {
            "type": "text",
            "content": output,
            "timestamp": datetime.now().isoformat()
        }
    
    async def terminate_session(self, session_id: str) -> bool:
        """세션 종료"""
        # CLI 세션 정보 정리
        if session_id in self.cli_sessions:
            cli_session = self.cli_sessions[session_id]
            logger.info(f"Terminating Claude CLI session {session_id} "
                       f"(turns: {cli_session.conversation_turns})")
            del self.cli_sessions[session_id]
        
        return await super().terminate_session(session_id)
    
    async def get_session_info(self, session_id: str) -> Optional[Dict]:
        """세션 정보 조회 (CLI 세션 정보 포함)"""
        info = await super().get_session_info(session_id)
        
        if info and session_id in self.cli_sessions:
            cli_session = self.cli_sessions[session_id]
            info.update({
                "claude_session_id": cli_session.claude_session_id,
                "conversation_turns": cli_session.conversation_turns,
                "last_command": cli_session.last_command,
                "claude_executable": self.claude_path
            })
        
        return info
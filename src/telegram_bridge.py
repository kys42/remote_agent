import asyncio
import logging
import json
import aiohttp
from typing import Dict, Optional
from datetime import datetime
import os
from dotenv import load_dotenv

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import config

load_dotenv()

logger = logging.getLogger(__name__)

class TelegramBridge:
    def __init__(self):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.agent_server_url = f"http://localhost:{os.getenv('EXECUTOR_PORT', 8001)}"
        self.user_sessions: Dict[str, str] = {}  # user_id -> session_id
        self.user_agents: Dict[str, str] = {}    # user_id -> agent_type
        self.active_executions: Dict[str, bool] = {}  # user_id -> is_executing
        
        # 허용된 사용자 ID 로드
        allowed_users_str = os.getenv('ALLOWED_USER_IDS', '')
        self.allowed_users = set(allowed_users_str.split(',')) if allowed_users_str else set()
        
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        
        # Application 설정
        self.application = Application.builder().token(self.token).build()
        
        # 핸들러 등록
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("agents", self.list_agents_command))
        self.application.add_handler(CommandHandler("new", self.new_session_command))
        self.application.add_handler(CommandHandler("switch", self.switch_agent_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("end", self.end_session_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
    
    def _is_user_allowed(self, user_id: str) -> bool:
        """사용자 접근 권한 확인"""
        # 허용된 사용자 목록이 비어있으면 모든 사용자 허용 (개발 모드)
        if not self.allowed_users:
            logger.warning(f"Access control not configured. User {user_id} accessing bot.")
            return True
        return user_id in self.allowed_users
    
    async def _check_access(self, update: Update) -> bool:
        """접근 권한 확인 및 거부 메시지 전송"""
        user_id = str(update.effective_user.id)
        user_name = update.effective_user.username or update.effective_user.first_name
        
        if not self._is_user_allowed(user_id):
            logger.warning(f"Unauthorized access attempt from user {user_id} ({user_name})")
            await update.message.reply_text(
                "❌ 접근 권한이 없습니다. 봇 관리자에게 문의하세요.\n"
                f"Your User ID: `{user_id}`",
                parse_mode='Markdown'
            )
            return False
        return True
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """시작 명령 처리"""
        if not await self._check_access(update):
            return
        
        user_id = str(update.effective_user.id)
        welcome_message = """
🤖 **원격 에이전트 실행 봇**에 오신 것을 환영합니다!

**사용 가능한 명령어:**
• `/start` - 봇 시작
• `/help` - 도움말 보기
• `/agents` - 사용 가능한 에이전트 목록
• `/new [에이전트] [디렉토리]` - 새 세션 시작
• `/switch [에이전트]` - 에이전트 변경
• `/status` - 현재 세션 상태 확인
• `/end` - 현재 세션 종료

메시지를 보내면 선택한 에이전트가 실행됩니다.
        """
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
        
        # 기본 에이전트로 세션 생성 (Claude Code)
        await self._create_session_for_user(user_id, "claude_code")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """도움말 명령 처리"""
        if not await self._check_access(update):
            return
        help_text = """
📖 **원격 에이전트 실행 봇 사용법**

**기본 명령어:**
• `/start` - 봇 시작 및 기본 세션 생성
• `/help` - 이 도움말 보기
• `/agents` - 사용 가능한 에이전트 목록 확인
• `/new [에이전트] [디렉토리]` - 새 세션 시작
• `/switch [에이전트]` - 다른 에이전트로 변경
• `/status` - 현재 세션 상태 확인
• `/end` - 현재 세션 종료

**사용 방법:**
1. `/agents` 명령으로 사용 가능한 에이전트 확인
2. `/new claude_code` 또는 `/new gemini_cli`로 원하는 에이전트 선택
3. 일반 메시지를 보내면 해당 에이전트가 실행됩니다

**예시:**
• `/new claude_code /home/user/project` - Claude Code로 특정 디렉토리에서 세션 시작
• `/switch gemini_cli` - Gemini CLI로 에이전트 변경
• "프로젝트의 README 파일을 작성해줘" - 에이전트에게 작업 요청

**지원하는 에이전트:**
• `claude_code` - Claude Code (기본)
• `gemini_cli` - Gemini CLI
• 기타 등록된 커스텀 에이전트

**주의사항:**
• 한 번에 하나의 명령만 실행 가능합니다
• 세션은 1시간 후 자동 종료됩니다
• 에이전트별로 별도 세션이 관리됩니다
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def list_agents_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """사용 가능한 에이전트 목록"""
        if not await self._check_access(update):
            return
        try:
            agents_info = await self._get_available_agents()
            
            if agents_info and "agents" in agents_info:
                agents_list = "\n".join([f"• `{agent}`" for agent in agents_info["agents"]])
                message = f"🤖 **사용 가능한 에이전트:** ({agents_info.get('total', 0)}개)\n\n{agents_list}"
            else:
                message = "❌ 에이전트 정보를 가져올 수 없습니다."
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error listing agents: {e}")
            await update.message.reply_text("❌ 에이전트 목록을 가져오는 중 오류가 발생했습니다.")
    
    async def new_session_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """새 세션 생성 명령 처리"""
        if not await self._check_access(update):
            return
        
        user_id = str(update.effective_user.id)
        
        # 기존 세션 종료
        if user_id in self.user_sessions:
            await self._terminate_session(user_id)
        
        # 파라미터 파싱
        agent_type = "claude_code"  # 기본값
        working_directory = None
        
        if context.args:
            agent_type = context.args[0]
            if len(context.args) > 1:
                working_directory = " ".join(context.args[1:])
        
        # 새 세션 생성
        session_id = await self._create_session_for_user(user_id, agent_type, working_directory)
        
        if session_id:
            msg = f"✅ 새 세션이 생성되었습니다.\n• 에이전트: `{agent_type}`\n• 세션 ID: `{session_id}`"
            if working_directory:
                msg += f"\n• 작업 디렉토리: `{working_directory}`"
        else:
            msg = f"❌ 세션 생성에 실패했습니다. 에이전트 `{agent_type}`이 사용 가능한지 확인하세요."
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    
    async def switch_agent_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """에이전트 변경 명령 처리"""
        if not await self._check_access(update):
            return
        
        user_id = str(update.effective_user.id)
        
        if not context.args:
            await update.message.reply_text("❌ 에이전트를 지정해주세요. 예: `/switch gemini_cli`", parse_mode='Markdown')
            return
        
        agent_type = context.args[0]
        
        # 현재 작업 디렉토리 유지
        working_directory = None
        if user_id in self.user_sessions:
            session_info = await self._get_session_info(self.user_sessions[user_id])
            if session_info:
                working_directory = session_info.get('working_directory')
        
        # 기존 세션 종료
        if user_id in self.user_sessions:
            await self._terminate_session(user_id)
        
        # 새 에이전트로 세션 생성
        session_id = await self._create_session_for_user(user_id, agent_type, working_directory)
        
        if session_id:
            msg = f"✅ 에이전트가 변경되었습니다.\n• 새 에이전트: `{agent_type}`\n• 세션 ID: `{session_id}`"
            if working_directory:
                msg += f"\n• 작업 디렉토리: `{working_directory}`"
        else:
            msg = f"❌ 에이전트 변경에 실패했습니다. `{agent_type}`이 사용 가능한지 확인하세요."
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """세션 상태 확인 명령 처리"""
        if not await self._check_access(update):
            return
        
        user_id = str(update.effective_user.id)
        
        if user_id not in self.user_sessions:
            await update.message.reply_text("❌ 활성 세션이 없습니다. `/new` 명령으로 새 세션을 생성하세요.", parse_mode='Markdown')
            return
        
        session_id = self.user_sessions[user_id]
        session_info = await self._get_session_info(session_id)
        
        if session_info:
            is_executing = self.active_executions.get(user_id, False)
            agent_type = self.user_agents.get(user_id, "unknown")
            
            status_msg = f"""
📊 **세션 상태**
• 에이전트: `{agent_type}`
• 세션 ID: `{session_id}`
• 생성 시간: `{session_info.get('created_at', 'N/A')}`
• 작업 디렉토리: `{session_info.get('working_directory', 'N/A')}`
• 실행 상태: {'🔄 실행 중' if is_executing else '✅ 대기 중'}
            """
        else:
            status_msg = "❌ 세션 정보를 가져올 수 없습니다."
        
        await update.message.reply_text(status_msg, parse_mode='Markdown')
    
    async def end_session_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """세션 종료 명령 처리"""
        if not await self._check_access(update):
            return
        
        user_id = str(update.effective_user.id)
        
        if user_id not in self.user_sessions:
            await update.message.reply_text("❌ 활성 세션이 없습니다.")
            return
        
        success = await self._terminate_session(user_id)
        
        if success:
            await update.message.reply_text("✅ 세션이 종료되었습니다.")
        else:
            await update.message.reply_text("❌ 세션 종료에 실패했습니다.")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """일반 메시지 처리 (에이전트 실행)"""
        if not await self._check_access(update):
            return
        
        user_id = str(update.effective_user.id)
        message_text = update.message.text
        
        # 세션 확인
        if user_id not in self.user_sessions:
            await update.message.reply_text("❌ 활성 세션이 없습니다. `/start` 명령으로 시작하세요.", parse_mode='Markdown')
            return
        
        # 이미 실행 중인지 확인
        if self.active_executions.get(user_id, False):
            await update.message.reply_text("⏳ 이미 명령이 실행 중입니다. 잠시 기다려주세요.")
            return
        
        session_id = self.user_sessions[user_id]
        agent_type = self.user_agents.get(user_id, "unknown")
        self.active_executions[user_id] = True
        
        try:
            # 실행 시작 알림
            status_message = await update.message.reply_text(f"🔄 {agent_type} 실행 중...")
            
            # 에이전트 실행
            output_messages = []
            async for output in self._execute_command(session_id, message_text):
                try:
                    if isinstance(output, str):
                        data = json.loads(output)
                    else:
                        data = output
                    
                    if "error" in data:
                        await context.bot.edit_message_text(
                            chat_id=update.effective_chat.id,
                            message_id=status_message.message_id,
                            text=f"❌ 오류: {data['error']}"
                        )
                        break
                    elif "content" in data:
                        output_messages.append(data['content'])
                    elif "type" in data and data["type"] == "text":
                        output_messages.append(data.get('content', str(data)))
                    
                except json.JSONDecodeError:
                    # JSON이 아닌 일반 텍스트
                    output_messages.append(str(output))
                except Exception as e:
                    logger.error(f"Error parsing output: {e}")
                    continue
            
            # 모든 출력 합치기
            if output_messages:
                full_output = "\n".join(output_messages)
                
                # 메시지 길이 제한 처리
                if len(full_output) > 4000:
                    chunks = [full_output[i:i+4000] for i in range(0, len(full_output), 4000)]
                    
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=status_message.message_id,
                        text=f"📤 **{agent_type} 출력** (1/{len(chunks)}):\n\n```\n{chunks[0]}\n```",
                        parse_mode='Markdown'
                    )
                    
                    for i, chunk in enumerate(chunks[1:], 2):
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=f"📤 **{agent_type} 출력** ({i}/{len(chunks)}):\n\n```\n{chunk}\n```",
                            parse_mode='Markdown'
                        )
                else:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=status_message.message_id,
                        text=f"📤 **{agent_type} 출력:**\n\n```\n{full_output}\n```",
                        parse_mode='Markdown'
                    )
            else:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=status_message.message_id,
                    text="✅ 실행 완료 (출력 없음)"
                )
            
            # 실행 완료 알림
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="✅ 실행 완료"
            )
            
        except Exception as e:
            logger.error(f"Error handling message from user {user_id}: {e}")
            await update.message.reply_text(f"❌ 오류가 발생했습니다: {str(e)}")
        
        finally:
            self.active_executions[user_id] = False
    
    async def _get_available_agents(self) -> Optional[Dict]:
        """사용 가능한 에이전트 목록 조회"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.agent_server_url}/agents") as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.error(f"Failed to get agents: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Error getting agents: {e}")
            return None
    
    async def _create_session_for_user(self, user_id: str, agent_type: str, working_directory: str = None) -> Optional[str]:
        """사용자를 위한 세션 생성"""
        try:
            async with aiohttp.ClientSession() as session:
                data = {
                    "agent_type": agent_type,
                    "user_id": user_id,
                    "working_directory": working_directory
                }
                
                async with session.post(f"{self.agent_server_url}/sessions", json=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        session_id = result["session_id"]
                        self.user_sessions[user_id] = session_id
                        self.user_agents[user_id] = agent_type
                        logger.info(f"Session created for user {user_id} with agent {agent_type}: {session_id}")
                        return session_id
                    else:
                        logger.error(f"Failed to create session for user {user_id}: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Error creating session for user {user_id}: {e}")
            return None
    
    async def _terminate_session(self, user_id: str) -> bool:
        """사용자 세션 종료"""
        if user_id not in self.user_sessions:
            return False
        
        session_id = self.user_sessions[user_id]
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(f"{self.agent_server_url}/sessions/{session_id}") as resp:
                    if resp.status == 200:
                        del self.user_sessions[user_id]
                        if user_id in self.user_agents:
                            del self.user_agents[user_id]
                        if user_id in self.active_executions:
                            del self.active_executions[user_id]
                        logger.info(f"Session terminated for user {user_id}: {session_id}")
                        return True
                    else:
                        logger.error(f"Failed to terminate session for user {user_id}: {resp.status}")
                        return False
        except Exception as e:
            logger.error(f"Error terminating session for user {user_id}: {e}")
            return False
    
    async def _get_session_info(self, session_id: str) -> Optional[Dict]:
        """세션 정보 조회"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.agent_server_url}/sessions/{session_id}") as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 404:
                        # 세션이 존재하지 않으면 로컬 상태에서 제거
                        self._cleanup_invalid_session(session_id)
                        return None
                    else:
                        return None
        except Exception as e:
            logger.error(f"Error getting session info for {session_id}: {e}")
            return None
    
    async def _execute_command(self, session_id: str, message: str):
        """명령 실행 및 스트리밍 출력"""
        try:
            async with aiohttp.ClientSession() as session:
                data = {
                    "session_id": session_id,
                    "message": message
                }
                
                async with session.post(f"{self.agent_server_url}/execute", json=data) as resp:
                    if resp.status == 200:
                        async for line in resp.content:
                            line_str = line.decode('utf-8').strip()
                            if line_str.startswith('data: '):
                                yield line_str[6:]  # 'data: ' 제거
                    else:
                        yield {"error": f"HTTP {resp.status}"}
        except Exception as e:
            logger.error(f"Error executing command: {e}")
            yield {"error": str(e)}
    
    def _cleanup_invalid_session(self, session_id: str):
        """유효하지 않은 세션 ID를 로컬 상태에서 제거"""
        user_to_remove = None
        for user_id, stored_session_id in self.user_sessions.items():
            if stored_session_id == session_id:
                user_to_remove = user_id
                break
        
        if user_to_remove:
            logger.info(f"Cleaning up invalid session {session_id} for user {user_to_remove}")
            del self.user_sessions[user_to_remove]
            if user_to_remove in self.user_agents:
                del self.user_agents[user_to_remove]
            if user_to_remove in self.active_executions:
                del self.active_executions[user_to_remove]
    
    async def run(self):
        """봇 실행"""
        logger.info("Starting Telegram Bridge...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        try:
            # 무한 대기
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Stopping Telegram Bridge...")
        finally:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

if __name__ == "__main__":
    bridge = TelegramBridge()
    asyncio.run(bridge.run())
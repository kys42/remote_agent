#!/usr/bin/env python3
"""
Remote Agent System - Main Entry Point

이 시스템은 텔레그램을 통해 다양한 AI 에이전트(Claude Code, Gemini CLI 등)를 
원격으로 실행할 수 있게 해주는 브릿지 시스템입니다.

사용법:
    python main.py --mode [bridge|server|both]
"""

import asyncio
import argparse
import logging
import os
import sys
from multiprocessing import Process
from dotenv import load_dotenv

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.agent_server import app as agent_app
from src.telegram_bridge import TelegramBridge

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_agent_server():
    """Agent Server 실행"""
    import uvicorn
    port = int(os.getenv('EXECUTOR_PORT', 8001))
    logger.info(f"Starting Agent Server on port {port}")
    uvicorn.run(agent_app, host="0.0.0.0", port=port, log_level="info")

async def run_telegram_bridge():
    """Telegram Bridge 실행"""
    logger.info("Starting Telegram Bridge")
    bridge = TelegramBridge()
    await bridge.run()

def run_bridge_process():
    """Telegram Bridge를 별도 프로세스에서 실행"""
    asyncio.run(run_telegram_bridge())

def main():
    parser = argparse.ArgumentParser(description="Remote Agent System")
    parser.add_argument(
        "--mode", 
        choices=["bridge", "server", "both"], 
        default="both",
        help="실행 모드: bridge(텔레그램만), server(에이전트 서버만), both(둘 다)"
    )
    
    args = parser.parse_args()
    
    # 환경 변수 검증
    required_env_vars = ['TELEGRAM_BOT_TOKEN']
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"다음 환경 변수가 필요합니다: {', '.join(missing_vars)}")
        logger.error("'.env' 파일을 생성하고 필요한 값들을 설정해주세요.")
        sys.exit(1)
    
    logger.info(f"Remote Agent System starting in {args.mode} mode...")
    
    if args.mode == "server":
        # Agent Server만 실행
        run_agent_server()
        
    elif args.mode == "bridge":
        # Telegram Bridge만 실행
        asyncio.run(run_telegram_bridge())
        
    elif args.mode == "both":
        # 둘 다 실행 (별도 프로세스)
        try:
            # Agent Server를 별도 프로세스에서 실행
            server_process = Process(target=run_agent_server)
            server_process.start()
            
            # Telegram Bridge를 메인 프로세스에서 실행
            asyncio.run(run_telegram_bridge())
            
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            if 'server_process' in locals():
                server_process.terminate()
                server_process.join()
        except Exception as e:
            logger.error(f"Error running system: {e}")
            if 'server_process' in locals():
                server_process.terminate()
                server_process.join()
            sys.exit(1)

if __name__ == "__main__":
    main()
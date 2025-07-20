#!/usr/bin/env python3
"""
Claude CLI Agent 테스트 스크립트
subprocess 기반의 claude -p 모드 사용 테스트
"""

import asyncio
import sys
import os
from datetime import datetime

# 프로젝트 경로 추가
sys.path.append('src')

from claude_cli_agent import ClaudeCodeCLIAgent
from agent_system import AgentConfig, AgentType

async def test_claude_cli_availability():
    """Claude CLI 사용 가능 여부 확인"""
    print("=== Claude CLI 사용 가능성 테스트 ===")
    
    try:
        config = AgentConfig(
            agent_type=AgentType.CLAUDE_CODE,
            executable_path="claude",  # 기본 경로
            default_args=[],
            timeout=300,
            max_sessions=1
        )
        
        agent = ClaudeCodeCLIAgent(config)
        print(f"✅ Claude CLI 발견: {agent.claude_path}")
        
        # 버전 확인
        import subprocess
        result = subprocess.run([agent.claude_path, '--version'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print(f"✅ Claude 버전: {result.stdout.strip()}")
        else:
            print(f"⚠️ 버전 확인 실패: {result.stderr}")
        
        return agent
        
    except FileNotFoundError:
        print("❌ Claude CLI를 찾을 수 없습니다.")
        print("설치 방법: npm install -g @anthropic-ai/claude-code")
        return None
    except Exception as e:
        print(f"❌ Claude CLI 테스트 실패: {e}")
        return None

async def test_simple_command(agent: ClaudeCodeCLIAgent):
    """간단한 명령어 테스트"""
    print("\n=== 간단한 명령어 테스트 ===")
    
    try:
        # 세션 생성
        session_id = await agent.create_session("test_user", os.getcwd())
        print(f"✅ 세션 생성: {session_id}")
        
        # 간단한 질문
        test_message = "안녕하세요! 현재 시간을 알려주세요."
        print(f"📝 테스트 메시지: {test_message}")
        print("--- 응답 스트림 ---")
        
        response_count = 0
        full_response = []
        
        async for result in agent.execute_command(session_id, test_message):
            response_count += 1
            timestamp = result.get('timestamp', datetime.now().isoformat())
            result_type = result.get('type', 'unknown')
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] #{response_count} - {result_type}")
            
            # 전체 결과 디버그 출력
            print(f"  🔍 전체 결과: {result}")
            
            # 콘텐츠 출력
            content = result.get('content', '')
            if content:
                full_response.append(content)
                display_content = content[:150] + "..." if len(content) > 150 else content
                print(f"  📄 콘텐츠: {display_content}")
            
            # 스트림 타입별 처리
            stream_type = result.get('stream_type')
            if stream_type:
                print(f"  📡 스트림: {stream_type}")
            
            # 에러 확인
            if 'error' in result:
                error_type = result.get('error_type', 'unknown')
                print(f"  ❌ 에러 ({error_type}): {result['error']}")
                break
            
            # 완료 확인
            if result_type == 'completion':
                return_code = result.get('return_code', 0)
                print(f"  ✅ 완료 (exit code: {return_code})")
                break
            
            print("-" * 50)
            
            # 무한 루프 방지
            if response_count > 20:
                print("⚠️ 너무 많은 응답으로 인해 중단됩니다.")
                break
        
        # 전체 응답 요약
        if full_response:
            print(f"\n📋 전체 응답 요약 ({len(full_response)}개 부분):")
            full_text = "\n".join(full_response)
            print(f"응답 길이: {len(full_text)} 문자")
            print(f"첫 200자: {full_text[:200]}")
            if len(full_text) > 200:
                print(f"마지막 200자: ...{full_text[-200:]}")
        else:
            print("⚠️ 응답 콘텐츠가 없습니다.")
        
        # 세션 정보 확인
        session_info = await agent.get_session_info(session_id)
        if session_info:
            print(f"세션 정보:")
            print(f"  - 대화 턴 수: {session_info.get('conversation_turns', 0)}")
            print(f"  - Claude 세션 ID: {session_info.get('claude_session_id', 'None')}")
        
        # 세션 종료
        await agent.terminate_session(session_id)
        print("✅ 세션 종료 완료")
        
    except Exception as e:
        print(f"❌ 명령어 테스트 실패: {e}")
        import traceback
        traceback.print_exc()

async def test_continue_conversation(agent: ClaudeCodeCLIAgent):
    """대화 연속성 테스트 (--continue 옵션)"""
    print("\n=== 대화 연속성 테스트 ===")
    
    try:
        # 세션 생성
        session_id = await agent.create_session("test_user", os.getcwd())
        print(f"✅ 세션 생성: {session_id}")
        
        # 첫 번째 메시지
        first_message = "파이썬에서 'hello world'를 출력하는 코드를 작성해주세요."
        print(f"📝 첫 번째 메시지: {first_message}")
        
        first_response = []
        async for result in agent.execute_command(session_id, first_message):
            print(f"  1️⃣ {result.get('type', 'unknown')}: {result}")
            
            content = result.get('content', '')
            if content:
                first_response.append(content)
                
            if result.get('type') == 'completion':
                print("✅ 첫 번째 응답 완료")
                break
            elif 'error' in result:
                print(f"❌ 첫 번째 메시지 에러: {result['error']}")
                return
        
        if first_response:
            full_first = "\n".join(first_response)
            print(f"📋 첫 번째 응답 ({len(full_first)} 문자): {full_first[:200]}...")
        
        # 두 번째 메시지 (이전 대화 참조)
        second_message = "그 코드를 함수로 만들어주세요."
        print(f"📝 두 번째 메시지 (연속): {second_message}")
        
        second_response = []
        context_found = False
        
        async for result in agent.execute_command(session_id, second_message):
            print(f"  2️⃣ {result.get('type', 'unknown')}: {result}")
            
            content = result.get('content', '')
            if content:
                second_response.append(content)
                if 'def' in content.lower() or 'function' in content.lower():
                    context_found = True
                    
            if result.get('type') == 'completion':
                print("✅ 두 번째 응답 완료")
                break
            elif 'error' in result:
                print(f"❌ 두 번째 메시지 에러: {result['error']}")
                break
        
        if second_response:
            full_second = "\n".join(second_response)
            print(f"📋 두 번째 응답 ({len(full_second)} 문자): {full_second[:200]}...")
            
        if context_found:
            print("✅ 연속 대화 성공! 이전 컨텍스트를 참조했습니다.")
        else:
            print("⚠️ 연속 대화에서 이전 컨텍스트 참조를 확인할 수 없습니다.")
        
        # 세션 종료
        await agent.terminate_session(session_id)
        print("✅ 연속성 테스트 완료")
        
    except Exception as e:
        print(f"❌ 연속성 테스트 실패: {e}")
        import traceback
        traceback.print_exc()

async def test_working_directory(agent: ClaudeCodeCLIAgent):
    """작업 디렉토리 테스트"""
    print("\n=== 작업 디렉토리 테스트 ===")
    
    try:
        # 현재 디렉토리에서 세션 생성
        session_id = await agent.create_session("test_user", os.getcwd())
        print(f"✅ 세션 생성 (작업 디렉토리: {os.getcwd()})")
        
        # 현재 디렉토리 파일 목록 요청
        message = "현재 디렉토리의 파일 목록을 보여주세요."
        print(f"📝 테스트 메시지: {message}")
        
        files_mentioned = []
        async for result in agent.execute_command(session_id, message):
            if result.get('type') == 'text':
                content = result.get('content', '')
                # 실제 존재하는 파일이 언급되는지 확인
                for file in os.listdir('.'):
                    if file in content:
                        files_mentioned.append(file)
            elif result.get('type') == 'completion':
                break
            elif 'error' in result:
                print(f"❌ 작업 디렉토리 테스트 에러: {result['error']}")
                break
        
        if files_mentioned:
            print(f"✅ 작업 디렉토리 인식 성공! 언급된 파일들: {files_mentioned[:3]}")
        else:
            print("⚠️ 작업 디렉토리를 정확히 인식하지 못했을 수 있습니다.")
        
        # 세션 종료
        await agent.terminate_session(session_id)
        print("✅ 작업 디렉토리 테스트 완료")
        
    except Exception as e:
        print(f"❌ 작업 디렉토리 테스트 실패: {e}")
        import traceback
        traceback.print_exc()

async def test_error_handling(agent: ClaudeCodeCLIAgent):
    """에러 처리 테스트"""
    print("\n=== 에러 처리 테스트 ===")
    
    try:
        # 잘못된 작업 디렉토리로 세션 생성 시도
        invalid_dir = "/nonexistent/directory"
        
        try:
            session_id = await agent.create_session("test_user", invalid_dir)
            message = "안녕하세요"
            
            error_detected = False
            async for result in agent.execute_command(session_id, message):
                if 'error' in result:
                    print(f"✅ 에러 감지: {result.get('error_type', 'unknown')} - {result['error']}")
                    error_detected = True
                    break
                elif result.get('type') == 'completion':
                    break
            
            if not error_detected:
                print("⚠️ 잘못된 디렉토리에서도 에러가 발생하지 않았습니다.")
            
            await agent.terminate_session(session_id)
            
        except Exception as e:
            print(f"✅ 예상된 에러 발생: {e}")
        
        print("✅ 에러 처리 테스트 완료")
        
    except Exception as e:
        print(f"❌ 에러 처리 테스트 실패: {e}")
        import traceback
        traceback.print_exc()

async def main():
    """메인 테스트 함수"""
    print("Claude CLI Agent 종합 테스트 시작\n")
    
    # CLI 사용 가능 여부 확인
    agent = await test_claude_cli_availability()
    
    if not agent:
        print("\n❌ Claude CLI를 사용할 수 없어 테스트를 중단합니다.")
        print("다음 명령어로 설치하세요: npm install -g @anthropic-ai/claude-code")
        return
    
    # 기본 명령어 테스트
    await test_simple_command(agent)
    
    # 대화 연속성 테스트
    await test_continue_conversation(agent)
    
    # 작업 디렉토리 테스트
    await test_working_directory(agent)
    
    # 에러 처리 테스트
    await test_error_handling(agent)
    
    print("\n🎉 모든 테스트 완료!")
    print("\nℹ️ 참고사항:")
    print("   - Claude CLI가 정상적으로 작동하려면 Anthropic API 키가 설정되어야 합니다")
    print("   - 일부 테스트는 네트워크 연결과 API 사용량에 따라 결과가 달라질 수 있습니다")

if __name__ == "__main__":
    asyncio.run(main())
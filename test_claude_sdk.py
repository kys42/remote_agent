#!/usr/bin/env python3
"""
공식 Claude Code SDK Agent 테스트 스크립트
개선된 버전으로 실제 SDK 구조에 맞게 작성됨
"""

import asyncio
import sys
import os
import json
from datetime import datetime

# 프로젝트 경로 추가
sys.path.append('src')

from claude_code_sdk_agent import ClaudeCodeSDKAgent
from agent_system import AgentConfig, AgentType

async def test_claude_sdk_agent():
    """공식 Claude SDK 에이전트 통합 테스트"""
    print("=== Claude Code SDK Agent 통합 테스트 ===")
    
    try:
        # 에이전트 설정
        config = AgentConfig(
            agent_type=AgentType.CLAUDE_CODE,
            executable_path="claude-code-sdk",  # SDK에서는 사용되지 않음
            default_args=[],
            timeout=300,
            max_sessions=1,
            stream_format='sdk'
        )
        
        # 에이전트 생성
        agent = ClaudeCodeSDKAgent(config)
        print("✅ Claude SDK Agent 생성 성공")
        
        # SDK 옵션 확인
        print(f"SDK 옵션:")
        print(f"  - Max turns: {agent.sdk_options.max_turns}")
        print(f"  - Permission mode: {agent.sdk_options.permission_mode}")
        print(f"  - Allowed tools: {', '.join(agent.sdk_options.allowed_tools)}")
        print(f"  - System prompt: {agent.sdk_options.system_prompt[:50]}...")
        
        # 테스트 세션 생성
        session_id = await agent.create_session("test_user", os.getcwd())
        print(f"✅ 세션 생성 성공: {session_id}")
        
        # 세션 정보 확인
        session_info = await agent.get_session_info(session_id)
        if session_info:
            print(f"세션 정보: {session_info.get('working_directory', 'Unknown')}")
        
        # 단순한 테스트 메시지 (실제 SDK 연결은 API 키가 필요하므로 에러 예상)
        test_message = "안녕하세요! 현재 시간을 알려주세요."
        print(f"\n📝 테스트 메시지: {test_message}")
        print("--- 응답 스트림 (에러 예상) ---")
        
        # 명령 실행 및 결과 출력
        response_count = 0
        async for result in agent.execute_command(session_id, test_message):
            response_count += 1
            timestamp = result.get('timestamp', datetime.now().isoformat())
            result_type = result.get('type', 'unknown')
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] #{response_count} - {result_type}")
            
            # 콘텐츠 출력
            content = result.get('content', '')
            if content:
                display_content = content[:150] + "..." if len(content) > 150 else content
                print(f"  콘텐츠: {display_content}")
            
            # 에러 처리
            if 'error' in result:
                error_type = result.get('error_type', 'unknown')
                print(f"  ❌ 에러 ({error_type}): {result['error']}")
                
                # CLI 미설치 에러인 경우 설치 안내
                if error_type == 'cli_not_found':
                    print("  ℹ️ 해결방법: npm install -g @anthropic-ai/claude-code")
                    break
            
            # AssistantMessage 상세 정보
            if result_type == 'assistant_message':
                print(f"  블록 수: {result.get('block_count', 0)}")
                if result.get('tool_uses'):
                    print(f"  도구 사용: {len(result['tool_uses'])}개")
            
            # 완료 메시지인 경우 루프 종료
            if result_type == 'completion':
                print(f"  수신 메시지 수: {result.get('message_count', 0)}")
                break
            
            print("-" * 50)
            
            # 무한 루프 방지
            if response_count > 10:
                print("⚠️ 너무 많은 응답으로 인해 중단됩니다.")
                break
        
        # 세션 정리
        await agent.terminate_session(session_id)
        print("✅ 세션 종료 완료")
        
    except Exception as e:
        print(f"❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()

async def test_sdk_message_parsing():
    """공식 SDK 메시지 파싱 테스트 (실제 SDK 타입들 사용)"""
    print("\n=== SDK 메시지 파싱 테스트 ===")
    
    try:
        # SDK가 사용 가능한지 먼저 확인
        from claude_code_sdk import AssistantMessage, TextBlock, ToolUseBlock
        
        config = AgentConfig(
            agent_type=AgentType.CLAUDE_CODE,
            executable_path="claude-code-sdk",
            default_args=[],
            timeout=300,
            max_sessions=1
        )
        
        agent = ClaudeCodeSDKAgent(config)
        
        # 실제 SDK 타입들로 테스트 메시지 생성
        test_cases = [
            {
                "name": "AssistantMessage with TextBlock",
                "message": type('AssistantMessage', (), {
                    '__class__': AssistantMessage,
                    'content': [type('TextBlock', (), {
                        '__class__': TextBlock,
                        'text': '안녕하세요! 도움이 필요한 일이 있나요?'
                    })()]
                })()
            },
            {
                "name": "AssistantMessage with ToolUse",
                "message": type('AssistantMessage', (), {
                    '__class__': AssistantMessage,
                    'content': [
                        type('TextBlock', (), {
                            '__class__': TextBlock,
                            'text': '파일을 읽어보겠습니다.'
                        })(),
                        type('ToolUseBlock', (), {
                            '__class__': ToolUseBlock,
                            'id': 'tool_123',
                            'name': 'Read',
                            'input': {'file_path': '/test/file.txt'}
                        })()
                    ]
                })()
            },
            {
                "name": "Unknown Message Type",
                "message": type('UnknownMessage', (), {
                    '__str__': lambda self: '알 수 없는 메시지 타입'
                })()
            }
        ]
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n테스트 {i}: {test_case['name']}")
            try:
                result = await agent.parse_sdk_message(test_case['message'])
                print(f"✅ 파싱 성공")
                print(f"   타입: {result['type']}")
                print(f"   콘텐츠: {result['content'][:50]}..." if len(result.get('content', '')) > 50 else f"   콘텐츠: {result.get('content', '')}")
                
                # AssistantMessage의 경우 더 상세한 정보 출력
                if result['type'] == 'assistant_message':
                    print(f"   텍스트 블록 수: {len(result.get('text_blocks', []))}")
                    print(f"   도구 사용 수: {len(result.get('tool_uses', []))}")
                    print(f"   전체 블록 수: {result.get('block_count', 0)}")
                
            except Exception as e:
                print(f"❌ 파싱 실패: {e}")
                import traceback
                traceback.print_exc()
    
    except ImportError as e:
        print(f"❌ SDK import 실패: {e}")
        print("실제 SDK가 설치되지 않았으므로 파싱 테스트를 건너뜁니다.")
    except Exception as e:
        print(f"❌ 파싱 테스트 실패: {e}")
        import traceback
        traceback.print_exc()

async def test_sdk_availability():
    """공식 Claude Code SDK 사용 가능 여부 및 버전 확인"""
    print("\n=== Claude Code SDK 사용 가능성 테스트 ===")
    
    try:
        # 기본 라이브러리 확인
        import anyio
        print(f"✅ anyio 버전: {anyio.__version__}")
        
        # Claude SDK 기본 구성요소 확인
        from claude_code_sdk import (
            query, 
            ClaudeCodeOptions,
            AssistantMessage,
            TextBlock,
            ToolUseBlock,
            ToolResultBlock,
            ClaudeSDKError,
            CLINotFoundError
        )
        print("✅ Claude Code SDK 기본 import 성공")
        
        # SDK 옵션 생성 테스트
        options = ClaudeCodeOptions(
            max_turns=1,
            system_prompt="Test system prompt",
            permission_mode='acceptEdits',
            allowed_tools=["Read", "Write"]
        )
        print("✅ ClaudeCodeOptions 생성 성공")
        print(f"  - Max turns: {options.max_turns}")
        print(f"  - Permission mode: {options.permission_mode}")
        print(f"  - Allowed tools: {', '.join(options.allowed_tools)}")
        
        # 메시지 타입 테스트
        test_text_block = type('TextBlock', (), {
            '__class__': TextBlock,
            'text': '테스트 텍스트 블록'
        })()
        print(f"✅ TextBlock 테스트: {test_text_block.text}")
        
        print("ℹ️ SDK가 올바르게 설치되었으나 실제 사용을 위해서는 Claude Code CLI와 API 키가 필요합니다.")
        
    except ImportError as e:
        print(f"❌ SDK import 실패: {e}")
        print("해결방법: pip install claude-code-sdk")
        print("참고: Claude Code CLI도 설치되어야 함 (npm install -g @anthropic-ai/claude-code)")
    except Exception as e:
        print(f"❌ SDK 테스트 실패: {e}")
        import traceback
        traceback.print_exc()

async def test_error_handling():
    """에러 처리 시나리오 테스트"""
    print("\n=== 에러 처리 테스트 ===")
    
    try:
        config = AgentConfig(
            agent_type=AgentType.CLAUDE_CODE,
            executable_path="claude-code-sdk",
            default_args=[],
            timeout=300,
            max_sessions=1
        )
        
        agent = ClaudeCodeSDKAgent(config)
        
        # 잘못된 메시지 타입 파싱 테스트
        print("잘못된 메시지 타입 파싱 테스트:")
        
        invalid_messages = [
            None,
            123,
            {"invalid": "data"},
            "plain string",
            []
        ]
        
        for i, invalid_msg in enumerate(invalid_messages, 1):
            print(f"\n테스트 {i}: {type(invalid_msg)} - {invalid_msg}")
            try:
                result = await agent.parse_sdk_message(invalid_msg)
                print(f"✅ 파싱 완료 (타입: {result['type']})")
            except Exception as e:
                print(f"❌ 파싱 에러: {e}")
        
        print("\n✅ 에러 처리 테스트 완료")
        
    except Exception as e:
        print(f"❌ 에러 처리 테스트 실패: {e}")
        import traceback
        traceback.print_exc()

async def main():
    """메인 테스트 함수"""
    print("공식 Claude Code SDK Agent 종합 테스트 시작\n")
    
    # SDK 사용 가능 여부 확인
    await test_sdk_availability()
    
    # 메시지 파싱 테스트
    await test_sdk_message_parsing()
    
    # 에러 처리 테스트
    await test_error_handling()
    
    # 실제 에이전트 테스트
    await test_claude_sdk_agent()
    
    print("\n🎉 모든 테스트 완료!")
    print("ℹ️ 실제 Claude SDK 사용을 위해서는 다음이 필요합니다:")
    print("   1. Claude Code CLI 설치: npm install -g @anthropic-ai/claude-code")
    print("   2. Anthropic API 키 설정")
    print("   3. 적절한 환경 변수 설정")

if __name__ == "__main__":
    asyncio.run(main())
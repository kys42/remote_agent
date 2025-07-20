#!/usr/bin/env python3
"""
Claude CLI 직접 테스트 스크립트 (디버깅용)
"""

import asyncio
import subprocess
import sys

async def test_claude_cli_direct():
    """Claude CLI를 직접 테스트"""
    print("=== Claude CLI 직접 테스트 ===")
    
    try:
        # 간단한 명령어 실행
        cmd = ['claude', '-p', '안녕하세요! 현재 시간을 알려주세요.']
        print(f"실행 명령어: {' '.join(cmd)}")
        
        # subprocess로 실행
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd="."
        )
        
        print("프로세스 시작됨, 출력 대기 중...")
        
        # stdout 읽기
        stdout_data, stderr_data = await process.communicate()
        
        print(f"Return code: {process.returncode}")
        print(f"STDOUT ({len(stdout_data)} bytes):")
        if stdout_data:
            print(stdout_data.decode('utf-8', errors='ignore'))
        else:
            print("(stdout 없음)")
            
        print(f"STDERR ({len(stderr_data)} bytes):")
        if stderr_data:
            print(stderr_data.decode('utf-8', errors='ignore'))
        else:
            print("(stderr 없음)")
        
    except FileNotFoundError:
        print("❌ claude 명령어를 찾을 수 없습니다.")
        print("설치: npm install -g @anthropic-ai/claude-code")
    except Exception as e:
        print(f"❌ 에러: {e}")
        import traceback
        traceback.print_exc()

async def test_claude_version():
    """Claude 버전 확인"""
    print("\n=== Claude 버전 확인 ===")
    
    try:
        # 버전 확인
        result = subprocess.run(['claude', '--version'], 
                              capture_output=True, text=True, timeout=10)
        
        print(f"Return code: {result.returncode}")
        if result.returncode == 0:
            print(f"Claude 버전: {result.stdout.strip()}")
        else:
            print(f"에러: {result.stderr}")
            
    except FileNotFoundError:
        print("❌ claude 명령어를 찾을 수 없습니다.")
    except subprocess.TimeoutExpired:
        print("❌ 타임아웃")
    except Exception as e:
        print(f"❌ 에러: {e}")

async def test_claude_help():
    """Claude 도움말 확인"""
    print("\n=== Claude 도움말 확인 ===")
    
    try:
        # 도움말 확인
        result = subprocess.run(['claude', '--help'], 
                              capture_output=True, text=True, timeout=10)
        
        print(f"Return code: {result.returncode}")
        if result.returncode == 0:
            help_text = result.stdout.strip()
            print(f"도움말 (첫 500자):")
            print(help_text[:500])
            
            # -p 옵션 확인
            if '-p' in help_text or '--print' in help_text:
                print("✅ -p/--print 옵션 사용 가능")
            else:
                print("⚠️ -p/--print 옵션을 찾을 수 없음")
        else:
            print(f"에러: {result.stderr}")
            
    except Exception as e:
        print(f"❌ 에러: {e}")

async def test_claude_streaming():
    """Claude CLI 스트리밍 테스트"""
    print("\n=== Claude CLI 스트리밍 테스트 ===")
    
    try:
        cmd = ['claude', '-p', 'Hello! Please tell me a short joke.']
        print(f"실행 명령어: {' '.join(cmd)}")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd="."
        )
        
        print("실시간 출력:")
        
        # 실시간으로 stdout 읽기
        line_count = 0
        while True:
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=5.0)
                if not line:
                    break
                
                line_count += 1
                text = line.decode('utf-8', errors='ignore').strip()
                if text:
                    print(f"  {line_count}: {text}")
                    
            except asyncio.TimeoutError:
                print("  (1초 타임아웃)")
                break
        
        # 프로세스 완료 대기
        return_code = await process.wait()
        print(f"프로세스 완료: exit code {return_code}")
        
        # 남은 stderr 확인
        stderr_data = await process.stderr.read()
        if stderr_data:
            print(f"STDERR: {stderr_data.decode('utf-8', errors='ignore')}")
        
    except Exception as e:
        print(f"❌ 스트리밍 테스트 에러: {e}")
        import traceback
        traceback.print_exc()

async def main():
    """메인 함수"""
    print("Claude CLI 디버그 테스트 시작\n")
    
    await test_claude_version()
    await test_claude_help()
    await test_claude_cli_direct()
    await test_claude_streaming()
    
    print("\n🔧 디버그 테스트 완료")

if __name__ == "__main__":
    asyncio.run(main())
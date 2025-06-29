#!/usr/bin/env python3
"""
Remote Agent System - Test Web UI with Streamlit
Agent Server와 통신하는 테스트용 웹 인터페이스

실행방법:
    streamlit run test_web_ui.py
"""

import streamlit as st
import requests
import json
import re
import time
import asyncio
import aiohttp
from typing import Dict, Optional, AsyncGenerator
import os
from dotenv import load_dotenv

load_dotenv()

# 설정
AGENT_SERVER_URL = f"http://localhost:{os.getenv('EXECUTOR_PORT', 8001)}"

# Streamlit 페이지 설정
st.set_page_config(
    page_title="Remote Agent Test UI",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS 스타일
st.markdown("""
<style>
.main-header {
    font-size: 2rem;
    font-weight: bold;
    color: #1f77b4;
    text-align: center;
    margin-bottom: 2rem;
}
.status-box {
    padding: 1rem;
    border-radius: 0.5rem;
    margin: 1rem 0;
}
.status-success {
    background-color: #d4edda;
    border: 1px solid #c3e6cb;
    color: #155724;
}
.status-error {
    background-color: #f8d7da;
    border: 1px solid #f5c6cb;
    color: #721c24;
}
.status-info {
    background-color: #d1ecf1;
    border: 1px solid #bee5eb;
    color: #0c5460;
}
</style>
""", unsafe_allow_html=True)

# 세션 상태 초기화
if 'session_id' not in st.session_state:
    st.session_state.session_id = None
if 'agent_type' not in st.session_state:
    st.session_state.agent_type = None
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'available_agents' not in st.session_state:
    st.session_state.available_agents = []
if 'input_key' not in st.session_state:
    st.session_state.input_key = 0

def get_available_agents() -> Optional[Dict]:
    """사용 가능한 에이전트 목록 조회"""
    try:
        response = requests.get(f"{AGENT_SERVER_URL}/agents", timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"에이전트 목록 조회 실패: HTTP {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"서버 연결 실패: {e}")
        return None

def create_session(agent_type: str, working_directory: str = None) -> Optional[str]:
    """새 세션 생성"""
    try:
        data = {
            "agent_type": agent_type,
            "user_id": "test_user",
            "working_directory": working_directory
        }
        
        response = requests.post(f"{AGENT_SERVER_URL}/sessions", json=data, timeout=30)
        if response.status_code == 200:
            result = response.json()
            return result["session_id"]
        else:
            st.error(f"세션 생성 실패: HTTP {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"세션 생성 중 오류: {e}")
        return None

def get_session_info(session_id: str) -> Optional[Dict]:
    """세션 정보 조회"""
    try:
        response = requests.get(f"{AGENT_SERVER_URL}/sessions/{session_id}", timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"세션 정보 조회 실패: {e}")
        return None

def terminate_session(session_id: str) -> bool:
    """세션 종료"""
    try:
        response = requests.delete(f"{AGENT_SERVER_URL}/sessions/{session_id}", timeout=5)
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        st.error(f"세션 종료 실패: {e}")
        return False

async def execute_command_async(session_id: str, message: str) -> AsyncGenerator[str, None]:
    """비동기 명령 실행 및 스트리밍"""
    try:
        async with aiohttp.ClientSession() as session:
            data = {
                "session_id": session_id,
                "message": message
            }
            
            async with session.post(f"{AGENT_SERVER_URL}/execute", json=data) as resp:
                if resp.status == 200:
                    async for line in resp.content:
                        line_str = line.decode('utf-8').strip()
                        if line_str.startswith('data: '):
                            yield line_str[6:]  # 'data: ' 제거
                else:
                    yield json.dumps({"error": f"HTTP {resp.status}"})
    except Exception as e:
        yield json.dumps({"error": str(e)})

def execute_command_sync(session_id: str, message: str) -> str:
    """동기 명령 실행 (간단한 테스트용)"""
    try:
        data = {
            "session_id": session_id,
            "message": message
        }
        
        response = requests.post(f"{AGENT_SERVER_URL}/execute", json=data, timeout=30, stream=True)
        
        def strip_ansi_codes(text):
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            return ansi_escape.sub('', text)

        if response.status_code == 200:
            output_parts = []
            for line in response.iter_lines(decode_unicode=True):
                if line.startswith('data: '):
                    try:
                        data_str = line[6:]
                        data_obj = json.loads(data_str)
                        
                        if "error" in data_obj:
                            return f"❌ 오류: {data_obj['error']}"
                        
                        content = data_obj.get("content", "")
                        if content:
                            # ANSI 코드 제거 후 추가
                            cleaned_content = strip_ansi_codes(str(content))
                            if cleaned_content.strip():
                                output_parts.append(cleaned_content)

                    except json.JSONDecodeError:
                        # JSON 파싱 실패 시 원본 데이터 추가 (디버깅용)
                        cleaned_line = strip_ansi_codes(line)
                        if cleaned_line.strip():
                            output_parts.append(f"[RAW] {cleaned_line}")
            
            return "\n".join(output_parts) if output_parts else "✅ 실행 완료 (출력 없음)"
        else:
            return f"❌ HTTP {response.status_code} 오류: {response.text}"
    except requests.exceptions.RequestException as e:
        return f"❌ 요청 실패: {e}"

# 메인 UI
st.markdown('<div class="main-header">🤖 Remote Agent Test UI</div>', unsafe_allow_html=True)

# 사이드바 - 세션 관리
with st.sidebar:
    st.header("🔧 세션 관리")
    
    # 서버 상태 확인
    with st.expander("📊 서버 상태", expanded=True):
        if st.button("🔄 상태 확인"):
            agents_info = get_available_agents()
            if agents_info:
                st.session_state.available_agents = agents_info.get("agents", [])
                st.markdown(f'<div class="status-box status-success">✅ 서버 연결됨<br>에이전트: {len(st.session_state.available_agents)}개</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="status-box status-error">❌ 서버 연결 실패</div>', unsafe_allow_html=True)
        
        if st.session_state.available_agents:
            st.write("**사용 가능한 에이전트:**")
            for agent in st.session_state.available_agents:
                st.write(f"• `{agent}`")
    
    # 세션 생성/관리
    with st.expander("🎯 세션 관리", expanded=True):
        if not st.session_state.session_id:
            st.write("**새 세션 생성**")
            
            # 에이전트 선택
            if st.session_state.available_agents:
                selected_agent = st.selectbox(
                    "에이전트 선택:",
                    st.session_state.available_agents,
                    index=0 if "claude_code" in st.session_state.available_agents else 0
                )
            else:
                selected_agent = st.text_input("에이전트 이름:", value="claude_code")
            
            # 작업 디렉토리
            working_dir = st.text_input("작업 디렉토리 (선택사항):", placeholder="/home/user/project")
            
            if st.button("🚀 세션 시작"):
                with st.spinner("세션 생성 중..."):
                    session_id = create_session(selected_agent, working_dir if working_dir else None)
                    if session_id:
                        st.session_state.session_id = session_id
                        st.session_state.agent_type = selected_agent
                        st.success(f"세션 생성됨: {session_id[:8]}...")
                        st.rerun()
        else:
            st.write("**현재 세션**")
            session_info = get_session_info(st.session_state.session_id)
            
            if session_info:
                st.write(f"**에이전트:** {st.session_state.agent_type}")
                st.write(f"**세션 ID:** `{st.session_state.session_id[:8]}...`")
                st.write(f"**생성 시간:** {session_info.get('created_at', 'N/A')}")
                if session_info.get('working_directory'):
                    st.write(f"**작업 디렉토리:** `{session_info['working_directory']}`")
                
                st.markdown('<div class="status-box status-success">🟢 세션 활성</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="status-box status-error">🔴 세션 정보 없음</div>', unsafe_allow_html=True)
            
            if st.button("🗑️ 세션 종료"):
                if terminate_session(st.session_state.session_id):
                    st.session_state.session_id = None
                    st.session_state.agent_type = None
                    st.session_state.chat_history = []
                    st.success("세션이 종료되었습니다.")
                    st.rerun()

# 메인 영역 - 채팅 인터페이스
if st.session_state.session_id:
    st.header(f"💬 {st.session_state.agent_type} 채팅")
    
    # 채팅 히스토리 표시
    chat_container = st.container()
    with chat_container:
        for i, (user_msg, agent_response) in enumerate(st.session_state.chat_history):
            with st.expander(f"💬 대화 #{i+1}", expanded=(i == len(st.session_state.chat_history) - 1)):
                st.markdown(f"**👤 사용자:** {user_msg}")
                st.markdown(f"**🤖 {st.session_state.agent_type}:**")
                st.code(agent_response if agent_response else "응답 없음", language="text")
    
    # 명령 입력
    st.markdown("---")
    
    def handle_send_message():
        user_input = st.session_state.get("user_input", "").strip()
        
        # 실행 중 상태 체크
        if st.session_state.get("is_executing", False):
            st.warning("⏳ 이미 실행 중입니다. 잠시 기다려주세요.")
            return
        
        if user_input:
            st.session_state.is_executing = True
            try:
                with st.spinner(f"🔄 {st.session_state.agent_type} 실행 중..."):
                    # 명령 실행
                    response = execute_command_sync(st.session_state.session_id, user_input)
                    
                    # 채팅 히스토리에 추가
                    st.session_state.chat_history.append((user_input, response))
                    
                    # 입력 필드 초기화
                    st.session_state.user_input = ""
            finally:
                st.session_state.is_executing = False

    user_input = st.text_area(
        "명령을 입력하세요:",
        height=100,
        placeholder="예: 현재 디렉토리의 파일 목록을 보여주세요",
        key="user_input"
    )
    
    col1, col2, col3 = st.columns([3, 1, 1])
    
    with col1:
        st.button("🚀 실행", on_click=handle_send_message, use_container_width=True)
    
    with col2:
        if st.button("🧹 히스토리 지우기", use_container_width=True):
            st.session_state.chat_history = []
            st.rerun()
    
    # 빠른 명령 버튼들
    st.markdown("**빠른 명령:**")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("📁 파일 목록"):
            response = execute_command_sync(st.session_state.session_id, "현재 디렉토리의 파일과 폴더를 보여주세요")
            st.session_state.chat_history.append(("현재 디렉토리의 파일과 폴더를 보여주세요", response))
            st.rerun()
    
    with col2:
        if st.button("📊 시스템 정보"):
            response = execute_command_sync(st.session_state.session_id, "시스템 정보를 알려주세요")
            st.session_state.chat_history.append(("시스템 정보를 알려주세요", response))
            st.rerun()
    
    with col3:
        if st.button("💾 Git 상태"):
            response = execute_command_sync(st.session_state.session_id, "git status를 확인해주세요")
            st.session_state.chat_history.append(("git status를 확인해주세요", response))
            st.rerun()
    
    with col4:
        if st.button("🐍 Python 버전"):
            response = execute_command_sync(st.session_state.session_id, "Python 버전을 확인해주세요")
            st.session_state.chat_history.append(("Python 버전을 확인해주세요", response))
            st.rerun()

else:
    st.info("👈 사이드바에서 세션을 시작하세요.")
    
    # 서버 상태 확인 UI
    st.markdown("---")
    st.header("🔍 서버 연결 테스트")
    
    if st.button("🔗 Agent Server 연결 테스트"):
        with st.spinner("서버 연결 확인 중..."):
            agents_info = get_available_agents()
            if agents_info:
                st.success("✅ Agent Server 연결 성공!")
                st.json(agents_info)
            else:
                st.error("❌ Agent Server 연결 실패")
                st.info(f"서버 주소: {AGENT_SERVER_URL}")
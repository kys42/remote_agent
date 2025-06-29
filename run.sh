#!/bin/bash

# Remote Agent System 실행 스크립트

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 로고 출력
echo -e "${BLUE}"
echo "=========================================="
echo "    Remote Agent System"
echo "=========================================="
echo -e "${NC}"

# 환경 확인
check_requirements() {
    echo -e "${YELLOW}환경 확인 중...${NC}"
    
    # Python 확인
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}Error: Python 3이 설치되어 있지 않습니다.${NC}"
        exit 1
    fi
    
    # pip 확인
    if ! command -v pip &> /dev/null && ! command -v pip3 &> /dev/null; then
        echo -e "${RED}Error: pip이 설치되어 있지 않습니다.${NC}"
        exit 1
    fi
    
    # .env 파일 확인
    if [ ! -f ".env" ]; then
        echo -e "${YELLOW}Warning: .env 파일이 없습니다. .env.example을 참조하여 생성해주세요.${NC}"
        echo -e "${BLUE}Creating .env from .env.example...${NC}"
        if [ -f ".env.example" ]; then
            cp .env.example .env
            echo -e "${GREEN}.env 파일이 생성되었습니다. 필요한 값들을 설정해주세요.${NC}"
        else
            echo -e "${RED}Error: .env.example 파일도 없습니다.${NC}"
            exit 1
        fi
    fi
    
    echo -e "${GREEN}환경 확인 완료${NC}"
}

# 의존성 설치
install_dependencies() {
    echo -e "${YELLOW}의존성 설치 중...${NC}"
    
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt
        echo -e "${GREEN}의존성 설치 완료${NC}"
    else
        echo -e "${RED}Error: requirements.txt 파일이 없습니다.${NC}"
        exit 1
    fi
}

# 도움말 표시
show_help() {
    echo -e "${BLUE}사용법:${NC}"
    echo "  $0 [OPTION]"
    echo ""
    echo -e "${BLUE}옵션:${NC}"
    echo "  start, run     - 전체 시스템 실행 (기본)"
    echo "  server         - Agent Server만 실행"
    echo "  bridge         - Telegram Bridge만 실행"
    echo "  install        - 의존성만 설치"
    echo "  check          - 환경 확인만 수행"
    echo "  help           - 도움말 표시"
    echo ""
    echo -e "${BLUE}예시:${NC}"
    echo "  $0 start       # 전체 시스템 실행"
    echo "  $0 server      # 에이전트 서버만 실행"
    echo "  $0 bridge      # 텔레그램 브릿지만 실행"
}

# 시스템 실행
run_system() {
    local mode=$1
    echo -e "${GREEN}Remote Agent System을 ${mode} 모드로 실행합니다...${NC}"
    python3 main.py --mode $mode
}

# 메인 로직
main() {
    local command=${1:-"start"}
    
    case $command in
        "start"|"run"|"")
            check_requirements
            install_dependencies
            run_system "both"
            ;;
        "server")
            check_requirements
            install_dependencies
            run_system "server"
            ;;
        "bridge")
            check_requirements
            install_dependencies
            run_system "bridge"
            ;;
        "install")
            check_requirements
            install_dependencies
            echo -e "${GREEN}설치 완료! 이제 $0 start로 시스템을 실행할 수 있습니다.${NC}"
            ;;
        "check")
            check_requirements
            echo -e "${GREEN}환경 확인 완료!${NC}"
            ;;
        "help"|"-h"|"--help")
            show_help
            ;;
        *)
            echo -e "${RED}알 수 없는 명령: $command${NC}"
            show_help
            exit 1
            ;;
    esac
}

# 스크립트 실행
main "$@"
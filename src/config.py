import json
import logging
import os
from typing import Dict, Any, Optional

class Config:
    """설정 파일 관리 클래스"""
    
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config = self._load_config()
        self._setup_logging()
    
    def _load_config(self) -> Dict[str, Any]:
        """설정 파일 로드"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"Warning: Config file {self.config_path} not found. Using defaults.")
            return self._get_default_config()
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in config file: {e}")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """기본 설정 반환"""
        return {
            "logging": {
                "level": "INFO",
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "file": None
            },
            "server": {
                "host": "0.0.0.0",
                "port": 8001,
                "timeout": 300
            },
            "agents": {
                "claude_code": {
                    "command": "claude_code",
                    "timeout": 300,
                    "max_output_lines": 1000
                },
                "gemini_cli": {
                    "command": "gemini_cli",
                    "timeout": 300,
                    "max_output_lines": 1000
                }
            },
            "telegram": {
                "message_chunk_size": 4000,
                "max_concurrent_users": 10
            }
        }
    
    def _setup_logging(self):
        """로깅 설정"""
        logging_config = self.config.get("logging", {})
        
        # 로깅 레벨 설정
        level_str = logging_config.get("level", "INFO")
        level = getattr(logging, level_str.upper(), logging.INFO)
        
        # 로깅 포맷 설정
        format_str = logging_config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        
        # 로깅 설정 적용
        logging.basicConfig(
            level=level,
            format=format_str,
            force=True  # 기존 설정 덮어쓰기
        )
        
        # 파일 로깅 설정 (선택사항)
        log_file = logging_config.get("file")
        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(level)
            file_handler.setFormatter(logging.Formatter(format_str))
            logging.getLogger().addHandler(file_handler)
    
    def get(self, key: str, default: Any = None) -> Any:
        """설정 값 가져오기 (점 표기법 지원)"""
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def get_logging_level(self) -> str:
        """로깅 레벨 반환"""
        return self.get("logging.level", "INFO")
    
    def get_server_config(self) -> Dict[str, Any]:
        """서버 설정 반환"""
        return self.get("server", {})
    
    def get_agent_config(self, agent_type: str) -> Dict[str, Any]:
        """에이전트 설정 반환"""
        return self.get(f"agents.{agent_type}", {})
    
    def get_telegram_config(self) -> Dict[str, Any]:
        """텔레그램 설정 반환"""
        return self.get("telegram", {})

# 전역 설정 인스턴스
config = Config()
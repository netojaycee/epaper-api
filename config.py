"""
Configuration management for FastAPI IDML News Extractor
Loads settings from environment variables with sensible defaults
"""

import os
import json
from typing import List, Union
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Application
    app_name: str = "IDML News Extractor API"
    app_env: str = Field(default="development", alias="APP_ENV")
    debug: bool = Field(default=False, alias="DEBUG")
    
    # Server
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    workers: int = Field(default=4, alias="WORKERS")
    
    # CORS - Allow requests from specific origins
    # For LAN access, add your local IP: "http://192.168.x.x:3000"
    # Use "*" to allow all origins (not recommended for production)
    allowed_origins: Union[List[str], str] = Field(
        default="http://localhost,http://localhost:3000,http://localhost:8000,http://127.0.0.1,http://127.0.0.1:3000,http://127.0.0.1:8000",
        alias="ALLOWED_ORIGINS"
    )
    
    # Allowed hosts for server (IP addresses that can connect)
    # Use "*" to allow all, or specify IPs: "192.168.1.100,localhost"
    allowed_hosts: Union[List[str], str] = Field(
        default="*",
        alias="ALLOWED_HOSTS"
    )
    
    # Allow credentials in CORS requests (cookies, auth headers)
    allow_credentials: bool = Field(default=True, alias="CORS_ALLOW_CREDENTIALS")
    
    # File uploads
    max_upload_size_mb: int = Field(default=100, alias="MAX_UPLOAD_SIZE_MB")
    temp_dir: str = Field(default="/tmp/epaper-uploads", alias="TEMP_DIR")
    
    # Ollama settings (for AI parser)
    ollama_host: str = Field(default="http://localhost:11434", alias="OLLAMA_HOST")
    ollama_model: str = Field(default="mistral", alias="OLLAMA_MODEL")
    
    # WordPress settings
    wp_url: str = Field(default="http://localhost/wp-json/wp/v2/posts", alias="WORDPRESS_URL")
    wp_user: str = Field(default="admin", alias="WORDPRESS_USERNAME")
    wp_password: str = Field(default="", alias="WORDPRESS_PASSWORD")
    wp_categories_url: str = Field(default="http://localhost/wp-json/wp/v2/categories?per_page=100", alias="WORDPRESS_CATEGORIES_URL")
    wp_authors_url: str = Field(default="http://localhost/wp-json/wp/v2/users?per_page=100", alias="WORDPRESS_AUTHORS_URL")
    wp_media_url: str = Field(default="http://localhost/wp-json/wp/v2/media", alias="WORDPRESS_MEDIA_URL")
    wp_enable_posting: bool = Field(default=False, alias="WORDPRESS_ENABLE_POSTING")
    
    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: str = Field(default="", alias="LOG_FILE")
    
    # Security
    require_auth: bool = Field(default=False, alias="REQUIRE_AUTH")
    api_key: str = Field(default="", alias="API_KEY")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # Ignore extra environment variables
    
    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v):
        """Parse ALLOWED_ORIGINS from JSON string or comma-separated list"""
        if isinstance(v, str):
            # Try JSON first
            if v.startswith("["):
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    pass
            # Try comma-separated
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v if isinstance(v, list) else [v]
    
    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, v):
        """Parse ALLOWED_HOSTS from JSON string or comma-separated list"""
        if isinstance(v, str):
            if v == "*":
                return ["*"]
            # Try JSON first
            if v.startswith("["):
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    pass
            # Try comma-separated
            return [host.strip() for host in v.split(",") if host.strip()]
        return v if isinstance(v, list) else [v]


# Global settings instance
settings = Settings()

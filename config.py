"""
Configuration management for FastAPI IDML News Extractor
Loads settings from environment variables with sensible defaults
"""

import os
from typing import List
from pydantic_settings import BaseSettings
from pydantic import Field


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
    
    # CORS
    allowed_origins: List[str] = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:8000",
    ]
    
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


# Global settings instance
settings = Settings()

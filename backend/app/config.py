import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # NVIDIA API
    NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")
    NVIDIA_MODEL: str = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
    
    # TTS settings
    TTS_PROVIDER: str = os.getenv("TTS_PROVIDER", "nvidia")
    TTS_MODEL: str = os.getenv("TTS_MODEL", "magpie-tts-multilingual")
    TTS_VOICE: str = os.getenv("TTS_VOICE", "mia")
    TTS_API_KEY: str = os.getenv("TTS_API_KEY", "")
    
    # STT settings
    STT_PROVIDER: str = os.getenv("STT_PROVIDER", "groq")
    STT_MODEL: str = os.getenv("STT_MODEL", "whisper-large-v3-turbo")
    STT_API_KEY: str = os.getenv("STT_API_KEY", "")
    
    # Application
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./real_estate.db")
    DEBUG: bool = True

settings = Settings()
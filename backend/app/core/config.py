"""Application configuration loaded from environment variables / .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    # Accepts both PostgreSQL DSNs and sqlite:/// for local dev without Docker.
    database_url: str = "postgresql://medikiosk:medikiosk@localhost:5432/medikiosk"

    # ── Auth ──────────────────────────────────────────────────────────────────
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # ── AI / LLM ──────────────────────────────────────────────────────────────
    # Main API path (hosted). Supports OpenAI and Gemini.
    # MAIN_LLM_PROVIDER: "openai" | "gemini"
    #   openai  — any OpenAI-compatible endpoint (OpenAI, Azure, Groq, Together…)
    #   gemini  — Google Gemini via its OpenAI-compatible endpoint. The key
    #             difference is that Gemini does not support response_format:
    #             json_object — we instruct it via the prompt instead.
    main_llm_provider: str = "openai"
    main_llm_api_key: str = ""
    main_llm_endpoint: str = ""  # blank → provider default endpoint is used
    main_llm_model: str = "gpt-4o-mini"

    # Local Offline path. Kept in separate settings from the Main API so the two
    # can be configured, and fail, independently.
    local_llm_endpoint: str = ""  # e.g. http://localhost:11434 (Ollama)
    local_llm_model: str = "llama3.2"

    # ── ASR / TTS ─────────────────────────────────────────────────────────────
    asr_api_key: str = ""
    asr_endpoint: str = ""
    tts_api_key: str = ""
    tts_endpoint: str = ""

    # ── Azure AI Services (all optional) ──────────────────────────────────────
    # Azure OpenAI — conversational AI, document analysis, summaries
    azure_openai_endpoint: str = ""  # https://<resource>.openai.azure.com
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4o"  # deployment name in Azure portal

    # Azure Speech Services — STT and TTS with native Hindi support
    azure_speech_key: str = ""
    azure_speech_region: str = "centralindia"

    # Azure Document Intelligence — high-quality OCR
    azure_doc_intelligence_endpoint: str = ""  # https://<resource>.cognitiveservices.azure.com
    azure_doc_intelligence_key: str = ""

    # ── ABDM / ABHA ───────────────────────────────────────────────────────────
    abha_sandbox_base_url: str = ""  # leave blank to use mock AuthProvider
    # FHIR endpoint the confirmed summary Bundle is POSTed to. Blank = generate
    # the Bundle but transmit nothing (the response says so explicitly).
    abdm_fhir_endpoint: str = ""

    # ── Data retention (DPDP) ─────────────────────────────────────────────────
    # Delete raw audio / document images once a summary reaches the HIS.
    purge_after_push: bool = True

    # ── Sarvam AI ─────────────────────────────────────────────────────────────
    # One key covers all three Sarvam services: Saaras (STT), Bulbul (TTS) and
    # Sarvam Vision (Document AI / OCR). STT and TTS read it from the environment
    # in app/interview/{asr,tts}.py; OCR reads it here.
    sarvam_api_key: str = ""
    # Document language hint, BCP-47. Note Document AI uses `language`, unlike the
    # STT/TTS endpoints which use `language_code`.
    sarvam_ocr_language: str = "en-IN"
    sarvam_ocr_model: str = "sarvam-vision-v1"
    # Document AI is an async job API. This caps how long a single OCR call will
    # wait for the job to reach a terminal state before giving up, so one slow
    # document cannot hold a kiosk upload open indefinitely.
    sarvam_ocr_timeout_seconds: int = 120
    sarvam_ocr_poll_seconds: float = 2.0

    # ── OCR / Google Cloud Vision ─────────────────────────────────────────────
    # Option A: API key (simpler, good for hackathon)
    google_vision_api_key: str = ""
    # Option B: Service account JSON file path (production)
    google_vision_credentials_path: str = ""  # path to service-account.json
    # Which OCR engine to use: "sarvam" | "tesseract" | "google_vision" | "azure"
    # Default is "sarvam" — it is a pure API call with no system dependencies, so
    # it works on any host (including Render). "tesseract" requires the tesseract
    # binary to be installed on the OS, which is not available on managed hosts.
    ocr_engine: str = "sarvam"

    # ── File storage ──────────────────────────────────────────────────────────
    file_storage_backend: str = "local"  # "local" | "supabase"
    file_storage_bucket: str = "medikiosk-documents"
    file_storage_root: str = "./storage"  # local disk path for demo

    # ── Supabase (when file_storage_backend=supabase) ─────────────────────────
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_bucket: str = "medikiosk-uploads"

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins. Defaults to local dev.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ── App meta ──────────────────────────────────────────────────────────────
    app_name: str = "MediKiosk"
    debug: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

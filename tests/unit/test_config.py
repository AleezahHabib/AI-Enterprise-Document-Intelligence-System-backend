"""Unit tests for BE-15 Configuration & Environment.
Named by requirement IDs per BE-16-R4.
"""

from pathlib import Path
import pytest
from pydantic import ValidationError
from app.core.config import Settings, AppEnv, LogLevel


def get_base_valid_env_dict():
    return {
        "DATABASE_URL": "postgresql://postgres:pwd@localhost:5432/postgres",
        "SUPABASE_URL": "https://test.supabase.co",
        "SUPABASE_SERVICE_KEY": "test_service_key",
        "GEMINI_API_KEY": "test_gemini_key",
    }


def test_be_15_r2_static_scan_os_environ_only_in_config():
    """BE-15-R2: Static scan finds os.environ only in config.py and migrate.py."""
    backend_app_dir = Path(__file__).parent.parent.parent / "app"
    forbidden_files = []
    
    for py_file in backend_app_dir.rglob("*.py"):
        if py_file.name == "config.py":
            continue
        content = py_file.read_text(encoding="utf-8")
        if "os.environ" in content or "os.getenv" in content:
            forbidden_files.append(str(py_file))

    assert len(forbidden_files) == 0, f"os.environ found in non-config modules: {forbidden_files}"


def test_be_15_r3_invalid_config_exits_nonzero(monkeypatch):
    """BE-15-R3: Missing required secret raises ValidationError."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)



def test_be_15_r6_port_6543_forces_zero_statement_cache():
    """BE-15-R6: Port 6543 forces statement_cache_size=0."""
    env = get_base_valid_env_dict()
    env["DATABASE_URL"] = "postgresql://postgres:pwd@pooler.supabase.com:6543/postgres"
    env["DB_STATEMENT_CACHE_SIZE"] = 100
    
    settings = Settings(**env)
    assert settings.DB_STATEMENT_CACHE_SIZE == 0


def test_be_15_r10_chunk_max_tokens_constraints_enforced():
    """BE-15-R10: Chunk max tokens, overlap, and min token bounds enforced."""
    env = get_base_valid_env_dict()
    
    # Overlap >= Target
    env_overlap = dict(env, CHUNK_OVERLAP_TOKENS=400, CHUNK_TARGET_TOKENS=400)
    with pytest.raises(ValidationError):
        Settings(**env_overlap)
        
    # Min > Target
    env_min = dict(env, CHUNK_MIN_TOKENS=500, CHUNK_TARGET_TOKENS=400)
    with pytest.raises(ValidationError):
        Settings(**env_min)
        
    # Max * 1.2 >= 2048
    env_max = dict(env, CHUNK_MAX_TOKENS=1800)
    with pytest.raises(ValidationError):
        Settings(**env_max)


def test_be_15_r11_retrieval_top_k_less_than_context_rejected():
    """BE-15-R11: RETRIEVAL_TOP_K < CONTEXT_CHUNKS is rejected."""
    env = get_base_valid_env_dict()
    env["RETRIEVAL_TOP_K"] = 4
    env["CONTEXT_CHUNKS"] = 8
    with pytest.raises(ValidationError):
        Settings(**env)


def test_be_15_r11_hnsw_ef_search_above_200_rejected():
    """BE-15-R11: HNSW_EF_SEARCH > 200 is rejected."""
    env = get_base_valid_env_dict()
    env["HNSW_EF_SEARCH"] = 250
    with pytest.raises(ValidationError):
        Settings(**env)


def test_be_15_r11_similarity_bounds_enforced():
    """BE-15-R11: Supporting similarity > Top similarity is rejected."""
    env = get_base_valid_env_dict()
    env["MIN_TOP_SIMILARITY"] = 0.40
    env["MIN_SUPPORTING_SIMILARITY"] = 0.50
    with pytest.raises(ValidationError):
        Settings(**env)


def test_be_15_r13_wildcard_allowed_origins_production_rejected():
    """BE-15-R13: ALLOWED_ORIGINS=* in production is rejected."""
    env = get_base_valid_env_dict()
    env["APP_ENV"] = AppEnv.PRODUCTION
    env["ALLOWED_ORIGINS"] = "*"
    with pytest.raises(ValidationError):
        Settings(**env)


def test_be_15_r15_env_example_covers_all_variables():
    """BE-15-R15: .env.example covers all variables defined in Settings."""
    env_example_file = Path(__file__).parent.parent.parent / ".env.example"
    assert env_example_file.exists(), ".env.example does not exist"
    
    content = env_example_file.read_text(encoding="utf-8")
    example_vars = set()
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            var_name = line.split("=")[0].strip()
            example_vars.add(var_name)
            
    # Check all fields from Settings
    settings_fields = set(Settings.model_fields.keys())
    missing_vars = settings_fields - example_vars
    assert not missing_vars, f".env.example missing fields: {missing_vars}"

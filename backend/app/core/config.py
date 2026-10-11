from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./sya.db"
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    UPLOAD_DIR: str = "./uploads"
    # Where the per-subject FAISS indexes live (one subdirectory per
    # subject_id). Configurable for the same reason DATABASE_URL is: the
    # test suite points it at its own directory, because ingestion is
    # keyed by subject_id and the fixtures use real-looking ids like
    # "CS101" - so with a single shared directory, running the tests
    # permanently mixed fixture chunks into the index the running app
    # grounds its lessons in (and vice versa).
    FAISS_INDEX_DIR: str = "./faiss_indexes"
    # Must include the origin the frontend is actually served from, or every
    # browser request is blocked before it reaches a route. 5500 is the port
    # the README/DOCUMENTATION tell you to run `python -m http.server` on, so
    # it has to be in the default list - the app has no .env out of the box,
    # so the default IS the configuration for a first run. The others cover
    # the dev servers (vite 5173, CRA/next 3000) this frontend is also served
    # from, and both spellings of localhost, since the browser treats
    # "localhost" and "127.0.0.1" as different origins.
    CORS_ORIGINS: str = (
        "http://localhost:5500,http://127.0.0.1:5500,"
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:8080,http://127.0.0.1:8080"
    )

    # llm generation settings (see llm_client.py). tries providers in this
    # order, first one that works wins. skips anything without an api key set.
    #   ollama  - local, free, needs ollama running on your machine
    #   mistral - cloud, free tier at console.mistral.ai
    #   groq    - cloud, free tier, fast, console.groq.com
    #   gemini  - cloud, free tier, aistudio.google.com/apikey
    LLM_PROVIDER_ORDER: str = "ollama,mistral,groq,gemini"

    MISTRAL_API_KEY: str = ""
    MISTRAL_MODEL: str = "mistral-small-latest"

    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.1-8b-instant"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"

    # pre-generate the first topic of each unit right after upload so it's
    # not waiting on a live llm call the first time someone opens it.
    # also generates the next topic in the background when one gets marked
    # complete. turn off if you want tighter control over api usage -
    # everything still generates fine on-demand either way
    PREGENERATE_UNIT_ENTRY_TOPICS: bool = True
    PREGENERATE_NEXT_ON_COMPLETE: bool = True

    # off by default because of real cost: generates EVERY topic in EVERY
    # unit right after distribution finishes, instead of just each unit's
    # first topic. makes the whole subject feel instantly ready the moment
    # extraction/distribution is done (no waiting on any topic, ever), but
    # it's one real llm call per topic whether or not anyone ever opens it.
    # for a 4 unit x 5 topic subject that's 20 calls guaranteed instead of
    # the ~4 unit-entry calls PREGENERATE_UNIT_ENTRY_TOPICS makes. turn on
    # if you want the "whole pipeline is realtime-ready" feel and don't
    # mind the extra api usage / longer time before the upload finishes
    # processing (this runs synchronously as part of the "generate" stage,
    # so a big syllabus will take noticeably longer to finish uploading
    # with this on).
    PREGENERATE_ALL_TOPICS: bool = False

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def llm_provider_order_list(self) -> List[str]:
        return [p.strip().lower() for p in self.LLM_PROVIDER_ORDER.split(",") if p.strip()]

    class Config:
        env_file = ".env"
        extra = "ignore"

@lru_cache()
def get_settings() -> Settings:
    return Settings()
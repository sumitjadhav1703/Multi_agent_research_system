# ResearchMind V1 (frozen Streamlit baseline)

The original Streamlit app: a sequential `search → reader → writer → critic` pipeline on Groq + Tavily.
It is kept for reference and regression visibility only (git tag `v1-baseline`). It is not deployed.
The live product is V2: `backend/` (FastAPI API), `frontend/` (console), `mcp-server/` (MCP Worker).

| File | Role |
| --- | --- |
| `app.py` | Streamlit UI |
| `pipeline.py` | Stage orchestration, pause/resume |
| `agents.py` | LangChain agents and chains |
| `tools.py` | Tavily search and bounded page scraping (uses the shared SSRF helper in `backend/app/security/`) |
| `style.css` | Streamlit theme |
| `tests/` | Offline tests (mocked providers) |
| `assets/` | Interface screenshots |

## Run

From the repo root, with Python 3.13:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r v1/requirements.txt
streamlit run v1/app.py
```

`GROQ_API_KEY` and `TAVILY_API_KEY` come from `.env` at the repo root.

## Test

```bash
cd v1 && python -m unittest discover -s tests
```

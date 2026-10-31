# ResearchMind

A Streamlit research workspace with four stages: search, read, write, and critique.
Built with LangChain, Groq (`openai/gpt-oss-20b`), Tavily, and BeautifulSoup.

[Open the deployed app](https://multiagentresearchsystem-f47mjoqmqw8nlxf8uud5v2.streamlit.app/)

## Run locally

Use Python **3.13** (the tested deployment version).

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# Edit .env and enter your own keys.
streamlit run app.py
```

Required secrets:

```dotenv
GROQ_API_KEY=your_groq_key
TAVILY_API_KEY=your_tavily_key
```

Never commit `.env` or `.streamlit/secrets.toml`. The landing page loads without
keys and explains missing configuration; research is disabled until both exist.

## Streamlit Community Cloud

1. Deploy `app.py` with Python 3.13 and the repository's `requirements.txt`.
2. In **App settings → Secrets**, add root-level TOML entries:

   ```toml
   GROQ_API_KEY = "your_groq_key"
   TAVILY_API_KEY = "your_tavily_key"
   ```
3. After merging changes, let Cloud rebuild. Reboot the app if the update has
   not appeared. Changing Python versions can require redeploying the app.

## Workflow and recovery

1. Enter a topic or choose a working example.
2. The Search agent queries Tavily. The Reader agent extracts one relevant
   public HTML source. The Writer creates a report with source links, and the
   Critic assesses the draft's clarity and evidence attribution.
3. Follow live stage status. Read the Report, Critic review, and Source material
   tabs; download the Markdown report as soon as writing completes.

Groq returns HTTP 429 when an organization-level request/token limit is reached.
The old implementation left this exception uncaught and could restart already
completed stages. The shared pipeline now preserves each completed stage,
shows a safe error, honors `Retry-After` (60-second fallback), and waits for an
explicit **Resume unfinished stages** action. Resuming a failed critic call
uses the existing report. Normal Streamlit reruns do not invoke the pipeline.
SDK retries are disabled; model output, input context, and agent loops are bounded.

This reduces repeated work; it does **not** increase your account quota or
coordinate usage across all visitors/workers. Daily quotas can require waiting
longer than the fallback cooldown. Check your account's
[Groq limits](https://console.groq.com/settings/limits) and the
[rate-limit documentation](https://console.groq.com/docs/rate-limits).

Results belong to the current browser session and saved topic. Starting a new
research run replaces them. Reloads that create a new session, session expiry,
or server restarts can lose them; download reports you want to keep.
A changed text field does not change the topic of an existing resumed run.

## CLI and tests

```bash
python pipeline.py
python -m unittest discover -s tests -v
```

The CLI shares the pipeline and prints a saved draft when review fails. Its
in-memory state lasts only for that process. Programmatic callers can pass a
mutable `state` dictionary to `run_research_pipeline(topic, state)` and reuse it
for the **same topic** after catching `PipelinePaused` and respecting its
`retry_after` value. The function retains its original return keys:
`search_results`, `scraped_content`, `report`, and `feedback`.

Tests mock external services and cover quota recovery, cooldown enforcement,
interrupted runs, reruns, empty topics, credential-free startup, clickable
examples, and public URL validation. CI runs the same suite on Python 3.13.
They do not establish live provider availability or research accuracy.

`requirements.in` contains direct dependencies; `requirements.txt` pins the
resolved dependency set. To intentionally update it, resolve and rerun tests:

```bash
uv pip compile requirements.in --python 3.13 -o requirements.txt
```

## Project files

- `app.py`, `style.css`, `.streamlit/config.toml`: interface and theme.
- `pipeline.py`: shared orchestration, saved stages, safe errors, cooldown metadata.
- `agents.py`: bounded Groq agents and writer/critic prompts; lazy clients.
- `tools.py`: Tavily search and bounded public-HTML extraction.
- `tests/`: offline pipeline, tool, and Streamlit interaction tests.

## Limits

AI reports and critic scores can be wrong; a critic review is not independent
fact checking. Source extraction covers one page, may fail on protected sites,
and cannot read PDFs. Extraction failures are disclosed to the report writer.
Fetched text is treated as untrusted evidence and is never rendered as raw HTML.

The scraper checks public IPs before each request and redirect, rejects embedded
credentials and non-web schemes, and bounds downloaded bytes. DNS validation
and connection resolution are separate: deploy behind a connection-time egress
policy before exposing it inside a private network. Prompt instructions and
agent loop bounds reduce abuse; they do not provide full prompt-injection isolation.

MIT license. See [LICENSE](LICENSE).

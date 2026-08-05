# LangSmith Tracing Setup & Usage

**Purpose**: Monitor and debug your Agentic RAG system in real-time using LangSmith observability platform.

---

## Quick Setup

### 1. Get LangSmith API Key

Visit [LangSmith](https://smith.langchain.com) and create a free account:

1. Sign up at https://smith.langchain.com
2. Navigate to Settings → API Keys
3. Create a new API key

### 2. Configure Environment Variables

In your `.env` file (already partially configured):

```bash
# Enable LangSmith tracing
LANGSMITH_TRACING=true

# Your API key from LangSmith
LANGSMITH_API_KEY=lsv2_pt_xxxxxxxxxxxxxxxxxxxxxxxxxxxx

# LangSmith endpoint (default is usually correct)
LANGSMITH_ENDPOINT=https://api.smith.langchain.com

# Project name for organizing traces
LANGSMITH_PROJECT="Agentic_RAG"
```

### 3. Verify Configuration

```bash
# Test that tracing is configured
python -c "
from src.observability import is_tracing_enabled
if is_tracing_enabled():
    print('✅ LangSmith tracing is ENABLED')
else:
    print('❌ LangSmith tracing is DISABLED')
"
```

---

## Using Tracing

### Automatic Tracing (Enabled Globally)

Once configured, **all LangChain operations are automatically traced** when you use the CLI, API, or Streamlit app.

#### CLI
```bash
# Traces automatically sent to LangSmith
python -m src.cli ask "What is Self-RAG?" --mode crag -v
```

#### API
```bash
# Start server (tracing enabled)
python -m uvicorn src.api.server:app --reload

# Make request (automatically traced)
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is Self-RAG?", "mode": "crag"}'
```

#### Streamlit
```bash
# Traces automatically captured
streamlit run streamlit_app.py

# Interact with UI - each query is traced
```

### Manual Tracing in Code

Use the `traced_execution` context manager for custom tracing:

```python
from src.observability import traced_execution
from src.runner import run_agent

# Wrap code in context manager for custom tracing
with traced_execution("custom_workflow"):
    result = run_agent("What is Self-RAG?", mode="crag")
    print(result.answer)
```

---

## Viewing Traces in LangSmith

### 1. Open LangSmith Dashboard

Visit [https://smith.langchain.com](https://smith.langchain.com) and log in.

### 2. Select Your Project

Navigate to your project: **"Agentic_RAG"** (or whatever you set `LANGSMITH_PROJECT` to).

### 3. View Traces

Each execution appears as a trace with:

- **Input**: Question/query
- **Output**: Answer
- **Duration**: Execution time
- **Steps**: Agent decisions, retrievals, generations
- **Errors**: Any failures with stack traces

### Example Trace Structure

For a CRAG query:

```
Query: "What is Self-RAG?"
├── Route Decision
│   └── Selected: retrieve
├── Retrieval
│   └── Retrieved 4 documents
├── Grading
│   ├── Doc 1: Relevant (0.9)
│   ├── Doc 2: Relevant (0.8)
│   ├── Doc 3: Not Relevant (0.2) → Rewrite
│   └── Doc 4: Relevant (0.85)
├── Query Rewrite
│   └── Rewritten: "Explain Self-RAG grading mechanism"
├── Retry Retrieval
│   └── Retrieved 4 new documents
└── Generation
    └── Generated answer from top docs
```

---

## Trace Insights

### What Gets Traced

✅ **Automatically traced**:
- LLM calls (prompts, responses, tokens used)
- Tool calls (retrieval, web search, etc.)
- Agent decisions and reasoning
- State transitions in LangGraph
- Errors and retries

### Performance Metrics

Each trace shows:
- **Tokens Used**: Input + output tokens (useful for cost tracking)
- **Duration**: How long each step took
- **Model**: Which LLM was called
- **Temperature**: Sampling parameter used

---

## Configuration Options

### Environment Variables

```bash
# Enable/disable tracing
LANGSMITH_TRACING=true|false

# Your API key (required if tracing enabled)
LANGSMITH_API_KEY=lsv2_pt_...

# Where LangSmith is hosted (usually default)
LANGSMITH_ENDPOINT=https://api.smith.langchain.com

# Project name for organizing runs
LANGSMITH_PROJECT=Agentic_RAG

# Optional: Run name prefix
# LANGCHAIN_RUN_NAME=my_experiment
```

### Programmatic Configuration

```python
from src.config import settings
from src.observability import is_tracing_enabled

# Check current settings
print(f"Tracing enabled: {is_tracing_enabled()}")
print(f"Project: {settings.langsmith_project}")
print(f"Endpoint: {settings.langsmith_endpoint}")
```

---

## Common Use Cases

### 1. **Debug Why an Answer is Wrong**

1. Run query via CLI/UI
2. Open trace in LangSmith
3. See exactly which documents were retrieved
4. Check grading scores for each document
5. Review generation prompt and response

### 2. **Monitor Production Queries**

1. Deploy API with tracing enabled
2. All queries automatically logged
3. View dashboard to see:
   - Success rate
   - Average latency per mode
   - Token usage trends
   - Error patterns

### 3. **Compare Mode Performance**

Run same question through different modes:

```bash
python -m src.cli ask "What is Self-RAG?" --mode baseline
python -m src.cli ask "What is Self-RAG?" --mode crag
python -m src.cli ask "What is Self-RAG?" --mode agentic
```

Then in LangSmith, compare traces side-by-side:
- Which mode was faster?
- Which retrieved better documents?
- Which generated better answers?

### 4. **Cost Analysis**

In LangSmith dashboard:
- View total tokens per mode
- Calculate costs (OpenAI pricing)
- Identify expensive queries
- Optimize prompts to reduce tokens

---

## Troubleshooting

### Traces Not Appearing

**Problem**: Ran query but nothing shows in LangSmith dashboard

**Solutions**:

1. **Check tracing is enabled**
   ```bash
   python -c "from src.observability import is_tracing_enabled; print(is_tracing_enabled())"
   ```

2. **Verify API key is correct**
   - Copy API key again from LangSmith Settings
   - Update `.env` file
   - Restart application

3. **Check network connectivity**
   ```bash
   curl https://api.smith.langchain.com/health
   ```

4. **Verify project name exists**
   - Project auto-creates if it doesn't exist
   - But check LANGSMITH_PROJECT matches what you expect

### API Key Invalid Error

```bash
# ❌ Error: "Authentication failed"
```

**Solution**:
1. Regenerate API key in LangSmith
2. Copy the full key (including `lsv2_pt_` prefix)
3. Update `.env`
4. Restart application

### Too Many Traces

If you're seeing duplicate traces or too much data:

1. Reduce verbosity in `.env`:
   ```bash
   LANGSMITH_TRACING=false  # Disable for testing
   ```

2. Or filter in LangSmith dashboard
   - Use project filter
   - Use date range filter
   - Search by query text

---

## Production Deployment

### Best Practices

1. **Use environment variables**
   ```bash
   export LANGSMITH_TRACING=true
   export LANGSMITH_API_KEY=lsv2_pt_...
   export LANGSMITH_PROJECT=prod-agentic-rag
   ```

2. **Separate projects per environment**
   ```bash
   # Development
   LANGSMITH_PROJECT=agentic-rag-dev

   # Production
   LANGSMITH_PROJECT=agentic-rag-prod
   ```

3. **Monitor costs**
   - Use LangSmith dashboard
   - Set up alerts for high token usage
   - Review traces for optimization opportunities

4. **Keep API key secure**
   - Never commit to git
   - Use secrets management (AWS Secrets Manager, etc.)
   - Rotate periodically

---

## Integration with Code

### In Your Application

The observability module is automatically integrated:

```python
# src/cli.py
from src.observability import init_langsmith_tracing

def main():
    init_langsmith_tracing()  # Initializes tracing
    # ... rest of CLI code
```

```python
# src/api/server.py
from src.observability import init_langsmith_tracing

init_langsmith_tracing()  # Initialize on server startup

app = FastAPI(...)
```

```python
# streamlit_app.py
from src.observability import init_langsmith_tracing

init_langsmith_tracing()  # Initialize on app load

# ... rest of Streamlit code
```

### Custom Tracing

For specific operations:

```python
from src.observability import traced_execution

with traced_execution("custom_decomposition"):
    # This execution gets traced with custom name
    result = decompose_chain.invoke({"question": question})
```

---

## Costs

**LangSmith Pricing**:
- Free tier: Sufficient for development
- Paid tiers: For production volume
- See [smith.langchain.com/pricing](https://smith.langchain.com/pricing)

**Cost Optimization**:
1. Disable tracing for high-volume queries
2. Use sampling (trace only 10% of queries)
3. Review slow queries and optimize
4. Use cheaper models for some steps

---

## FAQ

**Q: Does tracing slow down my system?**  
A: Minimal overhead (~50-100ms per query). LangSmith uses async calls.

**Q: Can I trace without internet?**  
A: No, traces are sent to LangSmith servers. Requires internet connectivity.

**Q: How long are traces kept?**  
A: Free tier keeps traces for 7 days. Paid plans have longer retention.

**Q: Can I export traces?**  
A: Yes, LangSmith provides APIs to fetch and export traces.

**Q: How do I disable tracing for sensitive queries?**  
A: Set `LANGSMITH_TRACING=false` in environment, or remove API key.

---

## Next Steps

1. **Sign up at LangSmith**: https://smith.langchain.com
2. **Get API key** and add to `.env`
3. **Run a query**: `python -m src.cli ask "What is Self-RAG?" --mode crag`
4. **View trace** in LangSmith dashboard
5. **Explore insights** from the trace

---

**Happy tracing!** 🔍📊

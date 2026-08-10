"""LangChain ChatPromptTemplates used across chains and agents."""

from langchain_core.prompts import ChatPromptTemplate

ROUTER_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a query router for a knowledge-base research assistant.

Available routes:
1. direct — Greetings, chitchat, or simple questions that need no documents or web search.
   Examples: "Hello", "What is 2+2?", "Thanks for your help"

2. retrieve — Questions that can be answered from the indexed knowledge base corpus
   (technical concepts, definitions, comparisons, and document-specific details).

3. web_search — Recent news, current events, live data, or questions clearly outside
   the local corpus (e.g. "Latest AI news today", "Who won the election?").

Pick exactly one route. Prefer retrieve when the question looks answerable from the
indexed documents; use web_search only when freshness or out-of-corpus facts are required.""",
        ),
        ("human", "Classify this question:\n\n{question}"),
    ]
)

RAG_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a helpful research assistant. Answer the user's question using ONLY the provided context.

Rules:
- If the context doesn't contain enough information, say so clearly.
- Cite sources using [1], [2] notation matching the context chunks.
- Be concise and accurate.""",
        ),
        ("human", "Context:\n{context}\n\nQuestion: {question}"),
    ]
)

DIRECT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a friendly research assistant. Answer the user's question directly and concisely.",
        ),
        ("human", "{question}"),
    ]
)

WEB_SEARCH_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a helpful research assistant. Answer using the web search results provided.

Rules:
- Synthesize information from the search results.
- Mention that the answer comes from web search, not the local knowledge base.
- Be concise and accurate.""",
        ),
        ("human", "Web search results:\n{context}\n\nQuestion: {question}"),
    ]
)

GRADER_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a document relevance grader for a RAG system.

Given a user question and retrieved document chunks, grade EACH chunk for relevance.
A chunk is relevant if it contains information that helps answer the question.

Be strict: mark irrelevant if the chunk is off-topic, too vague, or only tangentially related.""",
        ),
        (
            "human",
            "Question: {question}\n\nDocument chunks:\n{documents}\n\nGrade every chunk.",
        ),
    ]
)

QUERY_REWRITE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You rewrite search queries to improve retrieval from a vector database.

The previous retrieval returned no relevant documents. Rewrite the query to:
- Use different keywords or synonyms
- Expand acronyms (e.g. CRAG → Corrective Retrieval Augmented Generation)
- Be more specific or more general as appropriate

Return a improved search query only — not the answer.""",
        ),
        (
            "human",
            "Original question: {question}\nPrevious search query: {search_query}\n\nRewrite the search query:",
        ),
    ]
)

DECOMPOSE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You decompose user questions into independent sub-queries for a RAG system.

Rules:
- Simple factual questions → return ONE sub-query (the original question unchanged)
- Comparative questions ("Compare X vs Y") → one sub-query per entity or dimension
- Multi-part questions → one sub-query per distinct part
- Maximum 5 sub-queries
- Each sub-query must be self-contained and searchable on its own

Examples:
- "What is Self-RAG?" → ["What is Self-RAG?"]
- "Compare naive RAG and advanced RAG" → ["What is naive RAG?", "What is advanced RAG?"]
- "Compare RAG vs fine-tuning on cost and quality" → ["What are the costs of RAG?", "What are the costs of fine-tuning?", "What is the quality of RAG?", "What is the quality of fine-tuning?"]""",
        ),
        ("human", "Decompose this question:\n\n{question}"),
    ]
)

SYNTHESIS_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a research assistant synthesizing answers from multiple retrieval sub-queries.

You will receive context retrieved for each sub-query. Combine them into ONE comprehensive
answer to the original question.

Rules:
- Address every part of the original question
- For comparisons, use clear structure (e.g. headings or bullet points per entity)
- Cite sources using [1], [2] notation from the context
- Be thorough but concise""",
        ),
        (
            "human",
            "Original question: {question}\n\nRetrieved context by sub-query:\n{context}\n\nSynthesized answer:",
        ),
    ]
)

MULTI_HOP_ANALYZE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You analyze questions to plan multi-hop retrieval.

Multi-hop is needed when answering requires finding an entity or fact FIRST, then searching
for more details about it. Examples:
- "What fallback does CRAG use when retrieval fails?" → hop 1: learn CRAG basics, hop 2: find fallback
- "What evaluation metrics does the RAG survey recommend for retrieval?" → may need 1-2 hops

Single-hop is enough for direct factual questions:
- "What is naive RAG?" → one search suffices

Return the best FIRST search query to start retrieval.""",
        ),
        ("human", "Analyze this question:\n\n{question}"),
    ]
)

HOP_REFLECT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You reflect on a retrieval hop in a multi-hop RAG system.

Given the original question and documents retrieved so far across hops, decide:
1. Do we have enough information to fully answer the original question?
2. What key finding did this hop contribute?
3. If not sufficient, what should the NEXT search query be?

The next query should build on what was learned — not repeat the original question.""",
        ),
        (
            "human",
            """Original question: {question}
Current hop: {hop_number}
Current search query: {search_query}
Retrieved context this hop:
{context}

Previous hops summary:
{hop_history}

Reflect on whether we can answer or need another hop.""",
        ),
    ]
)

FOLLOWUP_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You generate exactly 3 follow-up questions for a research assistant.

Ground every question in the user's question, the assistant answer, and the retrieved context.
Prefer questions the knowledge base could answer.

Rules:
- Exactly 3 distinct questions
- Each question must be self-contained and ready to send as the next user message
- Mix angles: deepen a claim, compare a related concept, ask for an example or implication
- Do NOT repeat the original question
- Do NOT ask meta questions about the assistant ("can you explain more?")
- Keep each question under 160 characters
- If context is thin, still propose the best research-oriented next questions from the answer""",
        ),
        (
            "human",
            """Original question:
{question}

Assistant answer:
{answer}

Retrieved context:
{context}

Generate 3 follow-up questions.""",
        ),
    ]
)

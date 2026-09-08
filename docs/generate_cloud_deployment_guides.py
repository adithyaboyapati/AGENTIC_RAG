#!/usr/bin/env python3
"""Generate AWS and Azure deployment PDFs for Agentic RAG."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

DOCS = Path(__file__).resolve().parent
PAGE = A4
MARGIN = 18 * mm

AWS = {
    "name": "AWS",
    "accent": HexColor("#FF9900"),
    "dark": HexColor("#232F3E"),
    "band": HexColor("#161E2D"),
    "soft": HexColor("#FFF6E8"),
    "row": HexColor("#F7F8FA"),
    "filename": "AWS_DEPLOYMENT_GUIDE.pdf",
    "title": "Agentic RAG — AWS Deployment Guide",
    "subtitle": "Service catalog and step-by-step production deployment",
}
AZURE = {
    "name": "Azure",
    "accent": HexColor("#0078D4"),
    "dark": HexColor("#0B1F33"),
    "band": HexColor("#001B3D"),
    "soft": HexColor("#E8F3FC"),
    "row": HexColor("#F5F8FB"),
    "filename": "AZURE_DEPLOYMENT_GUIDE.pdf",
    "title": "Agentic RAG — Azure Deployment Guide",
    "subtitle": "Service catalog and step-by-step production deployment",
}


def styles(theme: dict) -> dict:
    base = getSampleStyleSheet()
    s = {
        "cover_kicker": ParagraphStyle(
            "cover_kicker",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=theme["accent"],
            tracking=1.4,
            spaceAfter=8,
        ),
        "cover_title": ParagraphStyle(
            "cover_title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=26,
            leading=32,
            textColor=white,
            alignment=TA_LEFT,
            spaceAfter=10,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=12,
            leading=16,
            textColor=HexColor("#D6DCE4"),
            spaceAfter=6,
        ),
        "cover_meta": ParagraphStyle(
            "cover_meta",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=HexColor("#A8B3C2"),
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=20,
            textColor=theme["dark"],
            spaceBefore=14,
            spaceAfter=8,
            borderPadding=0,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=theme["dark"],
            spaceBefore=11,
            spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "h3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=14,
            textColor=HexColor("#334155"),
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.2,
            textColor=HexColor("#1F2937"),
            alignment=TA_JUSTIFY,
            spaceAfter=7,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            textColor=HexColor("#1F2937"),
            leftIndent=12,
            spaceAfter=3,
        ),
        "cell": ParagraphStyle(
            "cell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.2,
            leading=11,
            textColor=HexColor("#1F2937"),
        ),
        "cell_b": ParagraphStyle(
            "cell_b",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.2,
            leading=11,
            textColor=white,
        ),
        "cell_name": ParagraphStyle(
            "cell_name",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.2,
            leading=11,
            textColor=theme["dark"],
        ),
        "note": ParagraphStyle(
            "note",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.6,
            leading=12,
            textColor=HexColor("#334155"),
            leftIndent=6,
            rightIndent=6,
            spaceBefore=2,
            spaceAfter=8,
        ),
        "code": ParagraphStyle(
            "code",
            parent=base["Code"],
            fontName="Courier",
            fontSize=7.4,
            leading=10.2,
            textColor=HexColor("#0F172A"),
            leftIndent=4,
            rightIndent=4,
            spaceBefore=2,
            spaceAfter=8,
        ),
        "caption": ParagraphStyle(
            "caption",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=11,
            textColor=HexColor("#64748B"),
            spaceAfter=8,
        ),
        "toc": ParagraphStyle(
            "toc",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=16,
            textColor=HexColor("#1F2937"),
            leftIndent=4,
        ),
        "footer": ParagraphStyle(
            "footer",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=HexColor("#64748B"),
        ),
        "step": ParagraphStyle(
            "step",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=14,
            textColor=theme["dark"],
            spaceBefore=10,
            spaceAfter=4,
        ),
        "center": ParagraphStyle(
            "center",
            parent=base["Normal"],
            alignment=TA_CENTER,
            fontName="Helvetica",
            fontSize=9,
            textColor=HexColor("#64748B"),
        ),
        "right": ParagraphStyle(
            "right",
            parent=base["Normal"],
            alignment=TA_RIGHT,
            fontName="Helvetica",
            fontSize=8,
            textColor=HexColor("#64748B"),
        ),
    }
    return s


def p(text: str, style) -> Paragraph:
    return Paragraph(text, style)


def bullets(items: list[str], st) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(i, st["bullet"]), leftIndent=8, bulletColor=HexColor("#475569")) for i in items],
        bulletType="bullet",
        start="circle",
        leftIndent=16,
        bulletFontSize=7,
        spaceAfter=8,
    )


def numbered(items: list[str], st) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(i, st["bullet"]), leftIndent=8) for i in items],
        bulletType="1",
        leftIndent=18,
        spaceAfter=8,
    )


def code_block(text: str, st) -> KeepTogether:
    block = Preformatted(text.strip("\n"), st["code"])
    data = [[block]]
    t = Table(data, colWidths=[PAGE[0] - 2 * MARGIN])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F1F5F9")),
                ("BOX", (0, 0), (-1, -1), 0.4, HexColor("#CBD5E1")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return KeepTogether([t, Spacer(1, 6)])


def note(text: str, st, theme: dict) -> KeepTogether:
    inner = Paragraph(text, st["note"])
    t = Table([[inner]], colWidths=[PAGE[0] - 2 * MARGIN])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), theme["soft"]),
                ("BOX", (0, 0), (-1, -1), 0.6, theme["accent"]),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return KeepTogether([t, Spacer(1, 6)])


def table(headers: list[str], rows: list[list[str]], st, theme: dict, widths: list[float | None] | None = None):
    usable = PAGE[0] - 2 * MARGIN
    if widths is None:
        widths = [usable / len(headers)] * len(headers)
    else:
        known = [w for w in widths if w is not None]
        missing = widths.count(None)
        rest = usable - sum(known)
        fill = rest / missing if missing else 0
        widths = [fill if w is None else w for w in widths]
    head = [Paragraph(h, st["cell_b"]) for h in headers]
    body = []
    for i, row in enumerate(rows):
        cells = []
        for j, val in enumerate(row):
            cells.append(Paragraph(val, st["cell_name"] if j == 0 else st["cell"]))
        body.append(cells)
    data = [head] + body
    t = Table(data, colWidths=widths, repeatRows=1)
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), theme["dark"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, HexColor("#E2E8F0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 1), (-1, -1), white),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), theme["row"]))
    t.setStyle(TableStyle(cmds))
    return KeepTogether([t, Spacer(1, 8)])


def cover(theme: dict, st, extra: str):
    story = []
    banner = Table(
        [
            [
                Paragraph("AGENTIC RAG &nbsp;&nbsp;|&nbsp;&nbsp; PRODUCTION CLOUD GUIDE", st["cover_kicker"]),
            ],
            [Paragraph(theme["title"], st["cover_title"])],
            [Paragraph(theme["subtitle"], st["cover_sub"])],
            [
                Paragraph(
                    "Application: Canonical Agentic RAG (FastAPI + React + Redis + ChromaDB)<br/>"
                    "Pipeline: canonical_pipeline_version = v1<br/>"
                    "Document date: 8 September 2026<br/>"
                    f"Cloud: {theme['name']}",
                    st["cover_meta"],
                )
            ],
        ],
        colWidths=[PAGE[0] - 2 * MARGIN],
    )
    banner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), theme["band"]),
                ("LEFTPADDING", (0, 0), (-1, -1), 16),
                ("RIGHTPADDING", (0, 0), (-1, -1), 16),
                ("TOPPADDING", (0, 0), (0, 0), 22),
                ("TOPPADDING", (0, 1), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -2), 4),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 20),
            ]
        )
    )
    story.append(banner)
    story.append(Spacer(1, 14))
    story.append(p("<b>What this document covers</b>", st["h2"]))
    story.append(
        p(
            "This guide maps the Agentic RAG repository onto a production-shaped "
            f"{theme['name']} topology. It lists every cloud service you need, why it exists, "
            "and a concrete ordered procedure to build, configure, ingest, and verify the stack. "
            "It is written against the current code: FastAPI in <font face='Courier'>src/api/server.py</font>, "
            "the React/nginx frontend, Redis cache and rate limits, Chroma HTTP, and the "
            "production boot checks in <font face='Courier'>ENVIRONMENT=production</font>.",
            st["body"],
        )
    )
    story.append(p(extra, st["body"]))
    story.append(p("<b>Contents</b>", st["h2"]))
    return story


def add_header_footer(canvas, doc, theme: dict):
    canvas.saveState()
    w, h = PAGE
    canvas.setFillColor(theme["band"])
    canvas.rect(0, h - 12 * mm, w, 12 * mm, fill=1, stroke=0)
    canvas.setFillColor(white)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(MARGIN, h - 7.5 * mm, "Agentic RAG")
    canvas.drawRightString(w - MARGIN, h - 7.5 * mm, theme["name"] + " Deployment Guide")
    canvas.setFillColor(HexColor("#F1F5F9"))
    canvas.rect(0, 0, w, 12 * mm, fill=1, stroke=0)
    canvas.setFillColor(HexColor("#64748B"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(MARGIN, 5 * mm, "Confidential operations document — do not paste secrets into this PDF")
    canvas.drawRightString(w - MARGIN, 5 * mm, f"Page {doc.page}")
    canvas.setStrokeColor(theme["accent"])
    canvas.setLineWidth(2)
    canvas.line(0, h - 12 * mm, w, h - 12 * mm)
    canvas.restoreState()


def app_context(st, theme: dict):
    story = []
    story.append(p("1. What you are deploying", st["h1"]))
    story.append(
        p(
            "Agentic RAG is not a notebook. Production is a multi-container service: a FastAPI "
            "agent runtime, a React UI that reverse-proxies <font face='Courier'>/api</font> and injects "
            "<font face='Courier'>X-API-Key</font> server-side, Redis for answer cache / rate limits / "
            "idempotency, and a Chroma HTTP server for embeddings. Optional pieces are Prometheus/"
            "Grafana, LangSmith tracing, NVIDIA rerank, Groq LLM failover, and Supabase (or a "
            "managed Postgres) for conversation memory and thumbs-up/down feedback.",
            st["body"],
        )
    )
    story.append(
        table(
            ["Workload", "Image / runtime", "Port", "Notes"],
            [
                [
                    "API",
                    "Repo <font face='Courier'>Dockerfile</font> (Python 3.10, uvicorn)",
                    "8000",
                    "Liveness <font face='Courier'>GET /health</font>. Readiness <font face='Courier'>/health/ready</font> is auth-gated. SSE on <font face='Courier'>POST /query/stream</font> (idle up to 300s).",
                ],
                [
                    "Frontend",
                    "<font face='Courier'>frontend/Dockerfile</font> (nginx 1.27)",
                    "80",
                    "Proxies <font face='Courier'>/api/</font> to the API. Injects <font face='Courier'>API_KEY</font>. SSE buffering must stay off. Upload body 25 MB.",
                ],
                [
                    "Redis",
                    "redis:7 (managed service in cloud)",
                    "6379",
                    "Required in production for shared rate limits and cache. Password/auth token mandatory.",
                ],
                [
                    "Chroma",
                    "chromadb/chroma:0.6.3",
                    "8000",
                    "Set <font face='Courier'>CHROMA_MODE=http</font>. Persist the volume. Do not publish this port to the internet.",
                ],
                [
                    "Docs / SQLite",
                    "Shared file volume",
                    "—",
                    "PDFs, parent store, extra-source SQLite, eval DBs. In-process BM25 lives in the API.",
                ],
            ],
            st,
            theme,
            widths=[28 * mm, 48 * mm, 18 * mm, None],
        )
    )
    story.append(p("Production boot will refuse to start unless all of the following are true:", st["body"]))
    story.append(
        bullets(
            [
                "<font face='Courier'>OPENAI_API_KEY</font> is set.",
                "<font face='Courier'>API_KEY</font> is set and at least 32 characters (<font face='Courier'>openssl rand -hex 32</font>).",
                "<font face='Courier'>CORS_ORIGINS</font> lists real frontend origins — <font face='Courier'>*</font> is rejected.",
                "<font face='Courier'>API_WORKERS &gt; 1</font> only if <font face='Courier'>RATE_LIMIT_BACKEND=redis</font>.",
                "<font face='Courier'>TRUST_CLIENT_RBAC</font> stays <font face='Courier'>false</font>.",
            ],
            st,
        )
    )
    story.append(
        note(
            "<b>Scale-out constraint.</b> BM25, the semantic cache, and in-process ingest jobs are not "
            "shared across replicas. Keep <font face='Courier'>API_WORKERS=1</font> and a single API task "
            "until you move hybrid search to a managed vector store. Size "
            "<font face='Courier'>MAX_CONCURRENT_QUERIES</font> against your OpenAI concurrency, not against CPU.",
            st,
            theme,
        )
    )
    story.append(p("External systems the app already calls (not provisioned in the VPC):", st["body"]))
    story.append(
        table(
            ["System", "Used for", "Required?"],
            [
                ["OpenAI", "Chat completions + <font face='Courier'>text-embedding-3-small</font>", "Yes"],
                ["NVIDIA NIM (build.nvidia.com)", "Cross-encoder rerank if <font face='Courier'>RERANK_PROVIDER=nvidia</font>", "Recommended"],
                ["Groq", "LLM failover when OpenAI fails", "Optional"],
                ["LangSmith", "Parent-span traces <font face='Courier'>agent_request:&lt;mode&gt;</font>", "Optional"],
                ["DuckDuckGo", "Web fallback in the graph (circuit-broken)", "Optional"],
                ["Supabase", "Persistent chat memory + answer_feedback", "Optional; replace with managed Postgres"],
            ],
            st,
            theme,
            widths=[42 * mm, 85 * mm, 35 * mm],
        )
    )
    return story


def env_table(st, theme: dict, redis_example: str, chroma_host: str, cors: str, trusted: str):
    story = []
    story.append(p("Environment variables to set on the API", st["h2"]))
    story.append(
        table(
            ["Variable", "Production value"],
            [
                ["ENVIRONMENT", "production"],
                ["OPENAI_API_KEY", "from secrets manager / Key Vault"],
                ["API_KEY", "same 32+ char secret injected into frontend nginx"],
                ["REQUIRE_API_KEY", "true"],
                ["CORS_ORIGINS", cors],
                ["TRUSTED_HOSTS", trusted],
                ["TRUST_PROXY_HEADERS", "true (TLS terminates at the load balancer)"],
                ["CHROMA_MODE", "http"],
                ["CHROMA_HOST / CHROMA_PORT", f"{chroma_host} / 8000"],
                ["REDIS_URL", redis_example],
                ["CACHE_ENABLED", "true"],
                ["RATE_LIMIT_BACKEND", "redis"],
                ["API_WORKERS", "1"],
                ["PROTECT_METRICS_ENDPOINT", "true unless scraper is on a private network"],
                ["PROTECT_READINESS_ENDPOINT", "true — load balancer probes <font face='Courier'>/health</font> only"],
                ["NVIDIA_API_KEY", "if rerank stays on NVIDIA"],
                ["GROQ_API_KEY", "optional failover"],
                ["INGEST_ALLOWED_ROOTS", "/app/data"],
                ["REQUEST_TIMEOUT_SECONDS", "120"],
                ["STREAM_TIMEOUT_SECONDS", "300"],
                ["MAX_CONCURRENT_QUERIES", "8 (tune after a load test)"],
            ],
            st,
            theme,
            widths=[62 * mm, None],
        )
    )
    story.append(
        p(
            "Frontend container needs <font face='Courier'>API_UPSTREAM</font> (private API URL) and the "
            "<b>same</b> <font face='Courier'>API_KEY</font>. The browser never holds the key; nginx injects "
            "<font face='Courier'>X-API-Key</font> and strips any client-supplied one.",
            st["body"],
        )
    )
    return story


def aws_steps(st, theme: dict):
    story = []
    story.append(p("2. Complete AWS service catalog", st["h1"]))
    story.append(p("2.1 Required services", st["h2"]))
    story.append(
        table(
            ["AWS service", "Role in this app", "Maps to compose"],
            [
                ["Amazon VPC + 2 AZs", "Private API/Redis/Chroma; public ALB only", "compose network"],
                ["Internet Gateway + NAT Gateway", "Inbound HTTPS; outbound OpenAI/NVIDIA/Groq", "host egress"],
                ["Security groups", "ALB 443; frontend 80 from ALB; API 8000 from frontend SG; Redis/Chroma internal", "expose vs ports"],
                ["Amazon ECR", "Store API and frontend images built from this repo", "docker build"],
                ["Amazon ECS (Fargate)", "Run API, frontend, and Chroma tasks", "compose services"],
                ["AWS Cloud Map", "Private DNS: api.rag.local, chroma.rag.local", "service names"],
                ["Elastic Load Balancing (ALB)", "HTTPS, host routing, SSE idle timeout 360s", "published 8080/8000"],
                ["AWS Certificate Manager", "Public TLS cert for the app hostname", "uncomment HSTS later"],
                ["Amazon Route 53", "A/AAAA alias to the ALB", "local hosts file"],
                ["Amazon ElastiCache (Redis 7)", "Cache, rate limits, idempotency keys", "redis service"],
                ["Amazon EFS", "Chroma persistence + /app/data (PDFs, SQLite, parent store)", "named volumes"],
                ["Amazon S3", "Source corpus, backups of chroma/parent_store", "data/sample_docs"],
                ["AWS Secrets Manager", "OPENAI_API_KEY, API_KEY, REDIS auth, NVIDIA, Groq, LangSmith", ".env.production"],
                ["Amazon CloudWatch Logs", "JSON stdout from API (production logging)", "compose logs"],
                ["Amazon CloudWatch Alarms", "5xx, unhealthy hosts, Redis CPU, OpenAI error spikes", "Grafana optional"],
                ["IAM roles", "Task execution (pull image, read secrets) + task role (S3/EFS)", "container user"],
            ],
            st,
            theme,
            widths=[48 * mm, 70 * mm, None],
        )
    )
    story.append(p("2.2 Strongly recommended", st["h2"]))
    story.append(
        table(
            ["AWS service", "Why"],
            [
                ["AWS WAF on the ALB", "Rate, bot, and SQLi/XSS managed rules in front of nginx"],
                ["AWS CloudTrail", "Audit who changed the cluster, secrets, and security groups"],
                ["Amazon GuardDuty", "Threat detection on the account"],
                ["AWS Backup", "EFS + S3 backup vault with retention"],
                ["Amazon RDS PostgreSQL", "Replace Supabase for chat_messages and answer_feedback (RLS still your job)"],
                ["Amazon CloudFront", "Optional CDN for hashed /assets/; keep /api on ALB with streaming"],
                ["AWS Managed Prometheus + Amazon Managed Grafana", "Scrape <font face='Courier'>/metrics</font> privately; import the repo dashboard"],
                ["AWS Budgets / Cost Anomaly Detection", "LLM spend is unbounded without MAX_TOKENS_* plus an account budget"],
            ],
            st,
            theme,
            widths=[62 * mm, None],
        )
    )
    story.append(p("2.3 Optional / later", st["h2"]))
    story.append(
        table(
            ["AWS service", "When to add it"],
            [
                ["Amazon EKS", "Only if you already run Kubernetes; Fargate ECS matches compose with less ops"],
                ["Amazon OpenSearch / Bedrock Knowledge Bases", "When BM25-in-process hits <font face='Courier'>BM25_MAX_DOCS</font> (20k)"],
                ["Amazon SQS + extra ingest worker", "When PDF batches exceed the in-process ingest queue"],
                ["AWS App Runner", "Not recommended: no private Redis/Chroma sidecar story"],
                ["Amazon EC2 (single host)", "Cheap staging: run the existing docker-compose.yml unchanged"],
            ],
            st,
            theme,
            widths=[62 * mm, None],
        )
    )

    story.append(p("3. Recommended topology", st["h1"]))
    story.append(
        p(
            "Use <b>ECS on Fargate</b> behind an internet-facing ALB. Put Redis and Chroma in private "
            "subnets. The React container is the only public target. Nginx talks to the API over Cloud Map. "
            "The API talks to ElastiCache and Chroma on the same VPC. NAT Gateway is required so Fargate "
            "tasks can reach OpenAI, NVIDIA, and Groq without public IPs.",
            st["body"],
        )
    )
    story.append(
        code_block(
            """
Internet
   │  HTTPS :443  (ACM cert, WAF optional)
   ▼
Application Load Balancer   idle timeout = 360s
   │  target group: frontend :80
   ▼
ECS Fargate  [frontend/nginx]
   │  API_UPSTREAM=http://api.rag.local:8000
   │  API_KEY from Secrets Manager
   ▼
ECS Fargate  [agentic-rag API :8000]     ── outbound via NAT ──► OpenAI / NVIDIA / Groq / LangSmith
   │
   ├── ElastiCache Redis (auth token, encryption in transit)
   ├── ECS Fargate [chroma :8000] + EFS /chroma/chroma
   └── EFS /app/data  (PDFs, parent_store.json, knowledge.db, feedback.db)

S3 bucket  rag-corpus  (source PDFs; copy into EFS or ingest from a one-off task)
Secrets Manager  /agentic-rag/prod/*
CloudWatch Logs  /ecs/agentic-rag-api
""",
            st,
        )
    )
    story.append(
        p(
            "Do <b>not</b> register the API, Redis, or Chroma as public ALB targets. The compose stack "
            "already follows this rule: only frontend 8080 and API 8000 are published locally, and even "
            "the API should stay private in AWS because nginx is the public edge.",
            st["body"],
        )
    )

    story.append(p("4. Prerequisites", st["h1"]))
    story.append(
        bullets(
            [
                "AWS account with billing alerts. Region example below: <font face='Courier'>us-east-1</font>.",
                "IAM principal that can create VPC, ECS, ECR, ElastiCache, EFS, ALB, ACM, Route 53, Secrets Manager.",
                "AWS CLI v2, Docker Desktop, and this git repo cloned.",
                "A DNS name you control (e.g. <font face='Courier'>rag.example.com</font>).",
                "OpenAI key; NVIDIA key if you keep cloud rerank; 32+ character app API key.",
                "Local sanity check already green: <font face='Courier'>pytest -q</font> and a Docker build of both images.",
            ],
            st,
        )
    )
    story.append(
        code_block(
            """
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export APP_HOST=rag.example.com
export API_KEY=$(openssl rand -hex 32)
aws configure list
""",
            st,
        )
    )

    story.append(p("5. Step-by-step deployment", st["h1"]))

    story.append(p("Step 1 — Create the network", st["step"]))
    story.append(
        p(
            "Create a VPC with two public and two private subnets across two AZs, an internet gateway, "
            "and a NAT Gateway in each AZ (or one NAT for cost, accepting the AZ risk). Tag it "
            "<font face='Courier'>agentic-rag-prod</font>. Enable DNS hostnames.",
            st["body"],
        )
    )
    story.append(
        p(
            "Console path: VPC → Create VPC → VPC and more → 2 AZs, 2 public, 2 private, NAT gateways. "
            "CLI users can use a CloudFormation/Terraform module; the exact IDs are referenced as "
            "<font face='Courier'>$VPC_ID $PUBLIC_SUBNETS $PRIVATE_SUBNETS</font> below.",
            st["body"],
        )
    )
    story.append(
        code_block(
            """
# Security groups (create after VPC exists)
aws ec2 create-security-group --group-name rag-alb-sg --description "ALB HTTPS" --vpc-id $VPC_ID
aws ec2 authorize-security-group-ingress --group-id $ALB_SG --protocol tcp --port 443 --cidr 0.0.0.0/0

aws ec2 create-security-group --group-name rag-frontend-sg --description "nginx from ALB" --vpc-id $VPC_ID
aws ec2 authorize-security-group-ingress --group-id $FE_SG --protocol tcp --port 80 --source-group $ALB_SG

aws ec2 create-security-group --group-name rag-api-sg --description "API from frontend" --vpc-id $VPC_ID
aws ec2 authorize-security-group-ingress --group-id $API_SG --protocol tcp --port 8000 --source-group $FE_SG

aws ec2 create-security-group --group-name rag-data-sg --description "Redis+Chroma from API" --vpc-id $VPC_ID
aws ec2 authorize-security-group-ingress --group-id $DATA_SG --protocol tcp --port 6379 --source-group $API_SG
aws ec2 authorize-security-group-ingress --group-id $DATA_SG --protocol tcp --port 8000 --source-group $API_SG
""",
            st,
        )
    )

    story.append(p("Step 2 — Container registry and images", st["step"]))
    story.append(
        p(
            "Create two ECR repositories. Chroma can keep using the public "
            "<font face='Courier'>chromadb/chroma:0.6.3</font> image (pin the digest in the task definition) "
            "or you can mirror it into ECR.",
            st["body"],
        )
    )
    story.append(
        code_block(
            """
aws ecr create-repository --repository-name agentic-rag-api --image-scanning-configuration scanOnPush=true --region $AWS_REGION
aws ecr create-repository --repository-name agentic-rag-frontend --image-scanning-configuration scanOnPush=true --region $AWS_REGION

aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

docker build -t $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/agentic-rag-api:v1 .
docker build -t $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/agentic-rag-frontend:v1 ./frontend

docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/agentic-rag-api:v1
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/agentic-rag-frontend:v1
""",
            st,
        )
    )
    story.append(
        note(
            "The API Dockerfile is multi-stage, non-root (<font face='Courier'>appuser</font>), and CI already "
            "fails if a <font face='Courier'>.env</font> is baked into the image. Never pass secrets as Docker "
            "<font face='Courier'>ARG</font>/<font face='Courier'>ENV</font> at build time.",
            st,
            theme,
        )
    )

    story.append(p("Step 3 — Secrets", st["step"]))
    story.append(
        code_block(
            """
aws secretsmanager create-secret --name agentic-rag/prod --secret-string "$(cat <<EOF
{
  "OPENAI_API_KEY": "sk-...",
  "API_KEY": "${API_KEY}",
  "NVIDIA_API_KEY": "nvapi-...",
  "GROQ_API_KEY": "",
  "LANGSMITH_API_KEY": "",
  "REDIS_AUTH_TOKEN": "$(openssl rand -hex 24)"
}
EOF
)"
""",
            st,
        )
    )
    story.append(
        p(
            "ECS task definitions should reference this secret with "
            "<font face='Courier'>valueFrom</font> per key. The frontend task only needs <font face='Courier'>API_KEY</font>.",
            st["body"],
        )
    )

    story.append(p("Step 4 — ElastiCache Redis", st["step"]))
    story.append(
        p(
            "Create a Redis 7 replication group in the private subnets, subnet group on $DATA_SG, "
            "transit encryption on, at-rest encryption on, AUTH token from the secret. Disable "
            "public access. Start with cache.t4g.small; this app uses Redis as a cache and token "
            "bucket, not as a primary database.",
            st["body"],
        )
    )
    story.append(
        code_block(
            """
# REDIS_URL the API expects (TLS example):
# rediss://:${REDIS_AUTH_TOKEN}@rag-redis.xxxxxx.cache.amazonaws.com:6379/0
#
# CACHE_ENABLED=true
# RATE_LIMIT_BACKEND=redis
""",
            st,
        )
    )

    story.append(p("Step 5 — EFS for Chroma and application data", st["step"]))
    story.append(
        p(
            "Create one EFS filesystem with mount targets in both private subnets, using $DATA_SG "
            "(add NFS 2049 from the API and Chroma security groups). Create two access points:",
            st["body"],
        )
    )
    story.append(
        bullets(
            [
                "<font face='Courier'>/chroma</font> — uid 1000, mounted at <font face='Courier'>/chroma/chroma</font> on the Chroma task.",
                "<font face='Courier'>/appdata</font> — uid 1000, mounted at <font face='Courier'>/app/data</font> on the API task (PDFs, parent_store, SQLite).",
            ],
            st,
        )
    )
    story.append(
        p(
            "Upload the sample corpus (or your PDFs) to S3, then copy onto EFS with a one-off Fargate task "
            "or AWS DataSync. The ingest CLI reads from <font face='Courier'>INGEST_ALLOWED_ROOTS=/app/data</font>.",
            st["body"],
        )
    )

    story.append(p("Step 6 — ECS cluster, namespace, and log groups", st["step"]))
    story.append(
        code_block(
            """
aws ecs create-cluster --cluster-name agentic-rag-prod --capacity-providers FARGATE FARGATE_SPOT \\
  --default-capacity-provider-strategy capacityProvider=FARGATE,weight=1

aws servicediscovery create-private-dns-namespace --name rag.local --vpc $VPC_ID --region $AWS_REGION

aws logs create-log-group --log-group-name /ecs/agentic-rag-api
aws logs create-log-group --log-group-name /ecs/agentic-rag-frontend
aws logs create-log-group --log-group-name /ecs/agentic-rag-chroma
""",
            st,
        )
    )
    story.append(
        p(
            "Create an IAM task execution role with AmazonECSTaskExecutionRolePolicy plus "
            "<font face='Courier'>secretsmanager:GetSecretValue</font> on <font face='Courier'>agentic-rag/prod</font>. "
            "Create a task role with EFS client and S3 read on the corpus bucket.",
            st["body"],
        )
    )

    story.append(p("Step 7 — Task definitions (order: Chroma → API → frontend)", st["step"]))
    story.append(p("<b>Chroma task</b> — 1 vCPU / 2 GB, image chromadb/chroma:0.6.3, port 8000, EFS mount, env:", st["body"]))
    story.append(
        code_block(
            """
IS_PERSISTENT=TRUE
ANONYMIZED_TELEMETRY=FALSE
# Service discovery name: chroma.rag.local
""",
            st,
        )
    )
    story.append(p("<b>API task</b> — 1 vCPU / 4 GB (embeddings + BM25 are memory-heavy), port 8000, EFS /app/data. Health check:", st["body"]))
    story.append(
        code_block(
            """
CMD-SHELL, python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=5).status==200 else 1)"
""",
            st,
        )
    )
    story.append(
        p(
            "Command stays the image default: uvicorn on 8000, <font face='Courier'>API_WORKERS=1</font>. "
            "CPU/memory: start 1024 CPU / 4096 MB. Hybrid retrieval loads chunks into RAM.",
            st["body"],
        )
    )
    story.append(p("<b>Frontend task</b> — 0.25 vCPU / 0.5 GB, port 80, env:", st["body"]))
    story.append(
        code_block(
            """
API_UPSTREAM=http://api.rag.local:8000
API_KEY=<from Secrets Manager>
""",
            st,
        )
    )

    story.append(p("Step 8 — Application Load Balancer", st["step"]))
    story.append(
        numbered(
            [
                "Create an internet-facing ALB in the public subnets, security group $ALB_SG.",
                "Create a target group <font face='Courier'>rag-frontend</font>, type IP, port 80, protocol HTTP, VPC private targets.",
                "Health check path <font face='Courier'>/</font> or <font face='Courier'>/index.html</font>, matcher 200.",
                "Request an ACM certificate for $APP_HOST (DNS validation in Route 53).",
                "HTTPS listener 443 → forward to rag-frontend. HTTP 80 → redirect to 443.",
                "<b>Idle timeout = 360 seconds</b> (Attributes). Default 60s will kill SSE streams "
                "(<font face='Courier'>STREAM_TIMEOUT_SECONDS=300</font> plus nginx 320s).",
                "Stickiness off. HTTP/2 on. Drop invalid headers on.",
            ],
            st,
        )
    )
    story.append(
        note(
            "If you later expose the API on a second host (api.example.com), create a second target group "
            "on port 8000 and probe <font face='Courier'>/health</font> only — never <font face='Courier'>/health/ready</font>, "
            "which is auth-gated and returns 401 to the load balancer.",
            st,
            theme,
        )
    )

    story.append(p("Step 9 — ECS services", st["step"]))
    story.append(
        p(
            "Create three Fargate services on private subnets, assign public IP <b>disabled</b>, "
            "use the matching security groups. Desired count: Chroma 1, API 1, frontend 2. "
            "Frontend can scale; API should stay at 1 replica until BM25 is externalized. "
            "Attach the frontend service to the ALB target group.",
            st["body"],
        )
    )
    story.append(
        code_block(
            """
# After services are RUNNING:
aws ecs update-service --cluster agentic-rag-prod --service frontend --desired-count 2
aws ecs update-service --cluster agentic-rag-prod --service api --desired-count 1
aws ecs update-service --cluster agentic-rag-prod --service chroma --desired-count 1
""",
            st,
        )
    )

    story.append(p("Step 10 — DNS", st["step"]))
    story.append(
        p(
            "In Route 53, alias A record $APP_HOST → ALB. Wait for ACM + DNS. Then set:",
            st["body"],
        )
    )
    story.append(
        code_block(
            """
CORS_ORIGINS=https://rag.example.com
TRUSTED_HOSTS=rag.example.com
TRUST_PROXY_HEADERS=true
""",
            st,
        )
    )
    story.append(
        p(
            "Redeploy the API after those three values change. Uncomment the HSTS header in "
            "<font face='Courier'>frontend/nginx.conf</font> once you confirm TLS is terminating in front of nginx, "
            "rebuild, and push a new frontend image.",
            st["body"],
        )
    )

    story.append(p("Step 11 — Ingest the knowledge base", st["step"]))
    story.append(
        p(
            "Chroma starts empty. Run a one-off ECS task (same API image, same EFS, same secrets) "
            "that overrides the command:",
            st["body"],
        )
    )
    story.append(
        code_block(
            """
python -m src.ingestion.ingest --source /app/data/sample_docs
""",
            st,
        )
    )
    story.append(
        p(
            "Confirm readiness from a jump host or ECS exec (send the API key):",
            st["body"],
        )
    )
    story.append(
        code_block(
            """
curl -sS https://rag.example.com/api/health
curl -sS -H "X-API-Key: $API_KEY" https://rag.example.com/api/health/ready
# Expect chroma check "ok" with a non-zero document count.
""",
            st,
        )
    )
    story.append(
        p(
            "Ongoing uploads go through the UI (<font face='Courier'>POST /ingest/upload</font>) or "
            "<font face='Courier'>POST /ingest/jobs</font>. Re-ingest flushes Redis answer keys "
            "(<font face='Courier'>rag:v1:*</font>) so stale answers are not served.",
            st["body"],
        )
    )

    story.append(p("Step 12 — Observability and alarms", st["step"]))
    story.append(
        bullets(
            [
                "CloudWatch Logs metric filters on <font face='Courier'>error_code</font> and <font face='Courier'>Token usage</font>.",
                "ALB alarms: HTTPCode_Target_5XX, UnHealthyHostCount, TargetResponseTime p95.",
                "ElastiCache: EngineCPUUtilization, Evictions, CurrConnections.",
                "Optional: Amazon Managed Prometheus scrape of <font face='Courier'>http://api.rag.local:8000/metrics</font> "
                "with <font face='Courier'>PROTECT_METRICS_ENDPOINT=false</font> only on the private network "
                "(compose does this today).",
                "LangSmith: set <font face='Courier'>LANGSMITH_TRACING=true</font> and the project name; traces wrap classify → retrieve → generate.",
            ],
            st,
        )
    )

    story.append(p("Step 13 — CI/CD", st["step"]))
    story.append(
        p(
            "Keep GitHub Actions CI as the quality gate (<font face='Courier'>.github/workflows/ci.yml</font>: "
            "ruff, pytest, pip-audit, gitleaks, frontend build, Docker image assertions). Add a "
            "<b>deploy</b> workflow on the <font face='Courier'>prod</font> branch:",
            st["body"],
        )
    )
    story.append(
        numbered(
            [
                "OIDC to AWS (no long-lived access keys).",
                "Build and push API + frontend images tagged with the git SHA.",
                "Register new ECS task definitions.",
                "Update frontend and API services (rolling). Chroma usually stays put.",
                "Run the ingest one-off task only when the corpus or chunking config changed.",
                "Smoke: <font face='Courier'>GET /api/health</font> and a canonical <font face='Courier'>POST /api/query</font>.",
            ],
            st,
        )
    )

    story.append(p("6. Verification", st["h1"]))
    story.append(
        code_block(
            """
# Liveness (no auth)
curl -i https://rag.example.com/api/health

# Chat via the public UI origin (nginx injects the key)
curl -N https://rag.example.com/api/query/stream \\
  -H "Content-Type: application/json" \\
  -d '{"question":"What is Self-RAG?","mode":"canonical"}'

# Expect SSE frames: step, token, answer, follow_ups, sources, done
# Browser: open https://rag.example.com, ask a question, confirm citations render.
""",
            st,
        )
    )
    story.append(
        p(
            "Also hit a cacheable question twice and confirm a <font face='Courier'>cache_hit</font> step on the second call. "
            "Then run a short Locust test from a jump host against staging, not production "
            "(<font face='Courier'>tests/load/locustfile.py</font>).",
            st["body"],
        )
    )

    story.append(p("7. Scaling, cost, and limits", st["h1"]))
    story.append(
        table(
            ["Knob", "Guidance"],
            [
                ["Frontend tasks", "Safe to autoscale 2–8 on ALB request count"],
                ["API tasks", "Keep 1 until hybrid search is a shared store; then Redis-backed rate limits allow N"],
                ["MAX_CONCURRENT_QUERIES", "Per replica. Total in-flight LLM calls = replicas × this value"],
                ["Chroma", "Single writer. Snapshot EFS. Vertical scale memory before adding replicas"],
                ["Redis", "TTL 3600s for answers; watch evictions after ingest flushes"],
                ["ALB idle timeout", "Must stay ≥ stream timeout or users see truncated SSE"],
            ],
            st,
            theme,
            widths=[48 * mm, None],
        )
    )
    story.append(
        p(
            "Order-of-magnitude monthly cost for a small production (us-east-1, light traffic): NAT Gateway "
            "dominates networking; Fargate 1×1vCPU/4GB API + 2×0.25 vCPU frontend + Chroma; ElastiCache "
            "t4g.small; ALB; EFS; Secrets Manager. LLM tokens on OpenAI will usually exceed the AWS bill. "
            "Set OpenAI project limits and the app token budgets together.",
            st["body"],
        )
    )

    story.append(p("8. Simpler staging path (EC2 + Compose)", st["h1"]))
    story.append(
        p(
            "If you only need a single-AZ staging box: launch Amazon Linux 2023 in a public subnet, "
            "install Docker, copy the repo, fill <font face='Courier'>.env.production</font> and compose "
            "<font face='Courier'>.env</font> (REDIS_PASSWORD, API_KEY, GRAFANA_ADMIN_PASSWORD), put an ALB "
            "or nginx with ACM in front of host port 8080, and run:",
            st["body"],
        )
    )
    story.append(
        code_block(
            """
cp .env.production.example .env.production   # chmod 600
# shell .env next to docker-compose.yml with REDIS_PASSWORD, API_KEY, GRAFANA_ADMIN_PASSWORD
docker compose up -d --build
python -m src.ingestion.ingest --source data/sample_docs   # or exec in the api container
""",
            st,
        )
    )
    story.append(
        p(
            "This is the same topology as <font face='Courier'>docs/PRODUCTION.md</font>. Promote to ECS when "
            "you need multi-AZ, managed Redis, and a deploy pipeline that does not SSH.",
            st["body"],
        )
    )

    story.append(p("9. Troubleshooting", st["h1"]))
    story.append(
        table(
            ["Symptom", "Likely cause", "Fix"],
            [
                ["API task never healthy", "Missing API_KEY / CORS=* / no OPENAI key", "Read CloudWatch: Unsafe production configuration"],
                ["ALB 504 on long chats", "Idle timeout 60s", "Set ALB idle timeout 360s; nginx already 320s"],
                ["401 on every UI call", "Frontend API_KEY ≠ API API_KEY", "One secret, two task definitions"],
                ["Empty answers / no sources", "Chroma empty", "Run ingest one-off; check /health/ready"],
                ["429 immediately", "Redis unreachable so budgets mis-share, or limits too low", "Check REDIS_URL; RATE_LIMIT_BACKEND=redis"],
                ["Slow first query", "Cold embeddings + NVIDIA rerank RTT", "Warm with a canary question after deploy"],
                ["OOM on API", "BM25 loaded full corpus", "Raise task memory or lower BM25_MAX_DOCS / move to OpenSearch"],
            ],
            st,
            theme,
            widths=[42 * mm, 55 * mm, None],
        )
    )

    story.append(p("10. Production checklist", st["h1"]))
    story.append(
        bullets(
            [
                "Secrets only in Secrets Manager; images contain no .env.",
                "Redis AUTH + encryption in transit; security groups least-privilege.",
                "Chroma and Redis not on the ALB.",
                "CORS and TRUSTED_HOSTS equal the real https origin.",
                "ALB idle timeout 360s; frontend HSTS enabled after TLS verified.",
                "CloudWatch alarms on 5xx, unhealthy hosts, Redis CPU.",
                "Ingest completed; /health/ready chroma ok.",
                "OpenAI billing cap + app MAX_TOKENS_PER_HOUR.",
                "Backup: EFS and S3. Restore drill once.",
                "Load test on staging. Locust file in tests/load.",
                "WAF associated. CloudTrail on. Budget alert on.",
            ],
            st,
        )
    )
    story.append(
        p(
            "Related repo docs: <font face='Courier'>docs/PRODUCTION.md</font>, "
            "<font face='Courier'>docs/ARCHITECTURE.md</font>, <font face='Courier'>docs/GUARDRAILS.md</font>, "
            "<font face='Courier'>docs/API.md</font>.",
            st["caption"],
        )
    )
    return story


def azure_steps(st, theme: dict):
    story = []
    story.append(p("2. Complete Azure service catalog", st["h1"]))
    story.append(p("2.1 Required services", st["h2"]))
    story.append(
        table(
            ["Azure service", "Role in this app", "Maps to compose"],
            [
                ["Resource group", "Single lifecycle for rag-prod", "project folder"],
                ["Azure Virtual Network", "Private API/Redis/Chroma; public ingress only", "compose network"],
                ["NAT Gateway", "Outbound to OpenAI / NVIDIA / Groq without public IPs on apps", "host egress"],
                ["Network security groups", "Allow 443 in; 80/8000/6379 only on app subnets", "expose vs ports"],
                ["Azure Container Registry", "API and frontend images", "docker build"],
                ["Azure Container Apps Environment", "Managed serverless Kubernetes under the hood", "compose project"],
                ["Container App: frontend", "nginx UI, external ingress", "frontend :8080"],
                ["Container App: api", "FastAPI, internal ingress only", "agentic-rag :8000"],
                ["Container App: chroma", "Chroma HTTP, internal ingress", "chroma"],
                ["Azure Cache for Redis", "Cache, rate limits, idempotency", "redis"],
                ["Azure Files (Premium)", "Chroma data + /app/data PDFs and SQLite", "named volumes"],
                ["Azure Blob Storage", "Source corpus and backups", "data/sample_docs"],
                ["Azure Key Vault", "OPENAI_API_KEY, API_KEY, Redis key, NVIDIA, Groq", ".env.production"],
                ["Managed identities", "Apps pull secrets and mount storage — no keys in env files", "IAM task role"],
                ["Azure DNS / App hostname", "https://rag.example.com on the frontend ingress", "local :8080"],
                ["Azure Monitor + Log Analytics", "stdout JSON logs, container metrics", "compose logs"],
            ],
            st,
            theme,
            widths=[50 * mm, 68 * mm, None],
        )
    )
    story.append(p("2.2 Strongly recommended", st["h2"]))
    story.append(
        table(
            ["Azure service", "Why"],
            [
                ["Azure Front Door (Standard/Premium) + WAF", "Global HTTPS, WAF, and optional CDN in front of Container Apps"],
                ["Azure Application Gateway", "Alternative regional L7 + WAF if you skip Front Door"],
                ["Azure Database for PostgreSQL Flexible Server", "Replace Supabase for chat_messages and answer_feedback"],
                ["Azure Monitor managed Prometheus + Azure Managed Grafana", "Scrape /metrics on the internal API"],
                ["Microsoft Defender for Cloud", "Registry scanning and runtime recommendations"],
                ["Azure Policy", "Deny public Redis, require HTTPS, require diagnostic settings"],
                ["Azure Budgets", "LLM spend plus Container Apps + Redis"],
                ["Azure Backup / Blob lifecycle", "Retain corpus and file-share snapshots"],
            ],
            st,
            theme,
            widths=[70 * mm, None],
        )
    )
    story.append(p("2.3 Optional / later", st["h2"]))
    story.append(
        table(
            ["Azure service", "When to add it"],
            [
                ["Azure Kubernetes Service (AKS)", "When you outgrow Container Apps (custom CNI, DaemonSets, GPU nodes)"],
                ["Azure AI Search / Azure OpenAI", "When you replace Chroma+OpenAI embeddings with Azure-native RAG"],
                ["Azure Service Bus", "When ingest jobs must survive API restarts (today the queue is in-process)"],
                ["Azure Container Apps jobs", "One-off ingest and eval_gates instead of exec into the API"],
                ["Azure App Service", "Not a good fit: SSE, sidecar Redis/Chroma, and custom nginx key injection"],
                ["Azure VM + docker compose", "Cheap staging; same as local PRODUCTION.md"],
            ],
            st,
            theme,
            widths=[70 * mm, None],
        )
    )

    story.append(p("3. Recommended topology", st["h1"]))
    story.append(
        p(
            "Use <b>Azure Container Apps</b> on a VNet-injected environment. Frontend ingress is "
            "external (or Front Door → internal). API and Chroma ingress are internal. Azure Cache "
            "for Redis is VNet-injected. Azure Files mounts provide durable Chroma and PDF storage. "
            "Key Vault plus user-assigned managed identities replace <font face='Courier'>.env.production</font> files.",
            st["body"],
        )
    )
    story.append(
        code_block(
            """
Internet
   │  HTTPS  (Front Door + WAF, or Container Apps built-in cert)
   ▼
Container App  frontend  (external)
   │  API_UPSTREAM=http://api.internal.<env>.azurecontainerapps.io
   │  API_KEY from Key Vault reference
   ▼
Container App  api  (internal only)   ── NAT ──► OpenAI / NVIDIA / Groq / LangSmith
   │
   ├── Azure Cache for Redis  (SSL, access key or Entra auth)
   ├── Container App  chroma  (internal) + Azure Files /chroma/chroma
   └── Azure Files  /app/data  (PDFs, parent_store.json, knowledge.db)

Storage account   corpus container (PDFs)
Key Vault         agentic-rag-prod
Log Analytics     workspace rag-prod
""",
            st,
        )
    )
    story.append(
        note(
            "Container Apps ingress idle timeout and HTTP/2 streaming: set "
            "<font face='Courier'>scale.rules</font> so the API replica is not scaled to zero, and raise "
            "the ingress timeout to cover <font face='Courier'>STREAM_TIMEOUT_SECONDS=300</font>. "
            "A scale-to-zero API will make the first chat look like an outage.",
            st,
            theme,
        )
    )

    story.append(p("4. Prerequisites", st["h1"]))
    story.append(
        bullets(
            [
                "Azure subscription with Owner or equivalent on a dedicated resource group.",
                "Azure CLI 2.x, Docker, this repo. Login: <font face='Courier'>az login</font>.",
                "DNS name you control, or accept the azurecontainerapps.io hostname for staging.",
                "OpenAI key; NVIDIA key if rerank stays NVIDIA; 32+ character app API key.",
                "Quota: Container Apps, Redis, Files Premium in the target region (example: eastus).",
            ],
            st,
        )
    )
    story.append(
        code_block(
            """
export LOC=eastus
export RG=rg-agentic-rag-prod
export ACR=acragenticrag$RANDOM
export ENV=cae-agentic-rag
export KV=kv-agentic-rag-prod
export APP_HOST=rag.example.com
export API_KEY=$(openssl rand -hex 32)
az account show
""",
            st,
        )
    )

    story.append(p("5. Step-by-step deployment", st["h1"]))

    story.append(p("Step 1 — Resource group and network", st["step"]))
    story.append(
        code_block(
            """
az group create -n $RG -l $LOC

az network vnet create -g $RG -n vnet-rag --address-prefix 10.20.0.0/16 \\
  --subnet-name snet-apps --subnet-prefix 10.20.1.0/24

az network vnet subnet create -g $RG --vnet-name vnet-rag -n snet-redis \\
  --address-prefix 10.20.2.0/24

az network vnet subnet create -g $RG --vnet-name vnet-rag -n snet-storage \\
  --address-prefix 10.20.3.0/24

az network nat gateway create -g $RG -n nat-rag -l $LOC
az network public-ip create -g $RG -n pip-nat --sku Standard --allocation-method Static
az network nat gateway public-ip associate -g $RG -n nat-rag --public-ip-address pip-nat
az network vnet subnet update -g $RG --vnet-name vnet-rag -n snet-apps --nat-gateway nat-rag
""",
            st,
        )
    )
    story.append(
        p(
            "Delegation: the apps subnet must be delegated to "
            "<font face='Courier'>Microsoft.App/environments</font> when you create the Container Apps "
            "environment with VNet injection. Redis subnet should use a private endpoint or VNet injection "
            "for Azure Cache for Redis (Premium).",
            st["body"],
        )
    )

    story.append(p("Step 2 — Azure Container Registry and images", st["step"]))
    story.append(
        code_block(
            """
az acr create -g $RG -n $ACR -l $LOC --sku Standard --admin-enabled false
az acr login -n $ACR

docker build -t $ACR.azurecr.io/agentic-rag-api:v1 .
docker build -t $ACR.azurecr.io/agentic-rag-frontend:v1 ./frontend
docker push $ACR.azurecr.io/agentic-rag-api:v1
docker push $ACR.azurecr.io/agentic-rag-frontend:v1

# Optional: import Chroma so production does not depend on Docker Hub at pull time
az acr import -n $ACR --source docker.io/chromadb/chroma:0.6.3 --image chroma:0.6.3
""",
            st,
        )
    )
    story.append(
        p(
            "Enable ACR vulnerability scanning (Defender) and lock the registry to the VNet if you use Premium. "
            "The Container Apps environment will use a user-assigned identity with AcrPull.",
            st["body"],
        )
    )

    story.append(p("Step 3 — Key Vault and identity", st["step"]))
    story.append(
        code_block(
            """
az keyvault create -g $RG -n $KV -l $LOC --enable-rbac-authorization true

az identity create -g $RG -n id-rag-apps
PRINCIPAL=$(az identity show -g $RG -n id-rag-apps --query principalId -o tsv)
ID_RES=$(az identity show -g $RG -n id-rag-apps --query id -o tsv)

# Grant the identity read on secrets (Key Vault Secrets User)
az role assignment create --assignee $PRINCIPAL --role "Key Vault Secrets User" \\
  --scope $(az keyvault show -n $KV -g $RG --query id -o tsv)

az keyvault secret set --vault-name $KV --name OPENAI-API-KEY --value "sk-..."
az keyvault secret set --vault-name $KV --name API-KEY --value "$API_KEY"
az keyvault secret set --vault-name $KV --name NVIDIA-API-KEY --value "nvapi-..."
az keyvault secret set --vault-name $KV --name REDIS-KEY --value "set-after-redis-exists"
""",
            st,
        )
    )

    story.append(p("Step 4 — Azure Cache for Redis", st["step"]))
    story.append(
        p(
            "Create a Standard or Premium C1 (or P1 if you need VNet injection / persistence). Enable TLS. "
            "Disable non-SSL port. Prefer a private endpoint on snet-redis. Then write the key into Key Vault "
            "and build the URL the API already understands:",
            st["body"],
        )
    )
    story.append(
        code_block(
            """
az redis create -g $RG -n redis-rag-prod -l $LOC --sku Standard --vm-size C1 --minimum-tls-version 1.2

# REDIS_URL example (SSL port 6380):
# rediss://:${REDIS_KEY}@redis-rag-prod.redis.cache.windows.net:6380/0
""",
            st,
        )
    )

    story.append(p("Step 5 — Storage (Blob + Azure Files)", st["step"]))
    story.append(
        code_block(
            """
az storage account create -g $RG -n stragprod$RANDOM -l $LOC --sku Premium_LRS --kind FileStorage
# Or a Standard_LRS account with both blob and file endpoints for staging

az storage share-rm create --storage-account <account> --name chroma-data --quota 100
az storage share-rm create --storage-account <account> --name app-data --quota 100
az storage container create --account-name <account> --name corpus
az storage blob upload-batch --account-name <account> -d corpus -s data/sample_docs
""",
            st,
        )
    )
    story.append(
        p(
            "Container Apps mount Azure Files as volumes. Mount chroma-data at "
            "<font face='Courier'>/chroma/chroma</font> on the Chroma app, and app-data at "
            "<font face='Courier'>/app/data</font> on the API. Copy PDFs from blob into the file share "
            "(AzCopy) before the first ingest job. UID in the API image is 1000 (appuser); set mount "
            "options so the process can write parent_store.json and SQLite files.",
            st["body"],
        )
    )

    story.append(p("Step 6 — Container Apps environment", st["step"]))
    story.append(
        code_block(
            """
az monitor log-analytics workspace create -g $RG -n law-rag -l $LOC
LAW_ID=$(az monitor log-analytics workspace show -g $RG -n law-rag --query customerId -o tsv)
LAW_KEY=$(az monitor log-analytics workspace get-shared-keys -g $RG -n law-rag --query primarySharedKey -o tsv)

az containerapp env create -g $RG -n $ENV -l $LOC \\
  --logs-workspace-id $LAW_ID --logs-workspace-key $LAW_KEY \\
  --infrastructure-subnet-resource-id <snet-apps-id>
""",
            st,
        )
    )
    story.append(
        p(
            "Turn on internal load balancer / VNet-only if Front Door is the public edge. Otherwise "
            "leave the environment with an external frontend app and internal API/Chroma apps.",
            st["body"],
        )
    )

    story.append(p("Step 7 — Deploy Chroma, API, then frontend", st["step"]))
    story.append(p("<b>Chroma</b> (min replicas 1, never 0):", st["body"]))
    story.append(
        code_block(
            """
az containerapp create -g $RG -n chroma --environment $ENV \\
  --image $ACR.azurecr.io/chroma:0.6.3 \\
  --ingress internal --target-port 8000 \\
  --cpu 1.0 --memory 2.0Gi --min-replicas 1 --max-replicas 1 \\
  --user-assigned $ID_RES \\
  --env-vars IS_PERSISTENT=TRUE ANONYMIZED_TELEMETRY=FALSE
# Attach Azure Files volume chroma-data -> /chroma/chroma
""",
            st,
        )
    )
    story.append(p("<b>API</b> (min replicas 1, 2.0 vCPU / 4Gi):", st["body"]))
    story.append(
        code_block(
            """
az containerapp create -g $RG -n api --environment $ENV \\
  --image $ACR.azurecr.io/agentic-rag-api:v1 \\
  --ingress internal --target-port 8000 --transport http \\
  --cpu 2.0 --memory 4.0Gi --min-replicas 1 --max-replicas 1 \\
  --user-assigned $ID_RES \\
  --registry-server $ACR.azurecr.io \\
  --secrets openai-key=keyvaultref:https://$KV.vault.azure.net/secrets/OPENAI-API-KEY,identityref:$ID_RES \\
            api-key=keyvaultref:https://$KV.vault.azure.net/secrets/API-KEY,identityref:$ID_RES \\
            nvidia-key=keyvaultref:https://$KV.vault.azure.net/secrets/NVIDIA-API-KEY,identityref:$ID_RES \\
            redis-url=keyvaultref:https://$KV.vault.azure.net/secrets/REDIS-URL,identityref:$ID_RES
""",
            st,
        )
    )
    story.append(
        p(
            "Non-secret env on the API: <font face='Courier'>ENVIRONMENT=production</font>, "
            "<font face='Courier'>CHROMA_MODE=http</font>, <font face='Courier'>CHROMA_HOST=&lt;chroma FQDN&gt;</font>, "
            "<font face='Courier'>CHROMA_PORT=8000</font>, <font face='Courier'>CACHE_ENABLED=true</font>, "
            "<font face='Courier'>RATE_LIMIT_BACKEND=redis</font>, <font face='Courier'>API_WORKERS=1</font>, "
            "<font face='Courier'>TRUST_PROXY_HEADERS=true</font>, "
            "<font face='Courier'>CORS_ORIGINS=https://$APP_HOST</font>, "
            "<font face='Courier'>TRUSTED_HOSTS=$APP_HOST</font>, "
            "<font face='Courier'>INGEST_ALLOWED_ROOTS=/app/data</font>, "
            "<font face='Courier'>PROTECT_READINESS_ENDPOINT=true</font>. "
            "Probes: liveness HTTP GET /health on 8000. Do not use /health/ready as the platform probe.",
            st["body"],
        )
    )
    story.append(p("<b>Frontend</b> (external ingress, min 2):", st["body"]))
    story.append(
        code_block(
            """
az containerapp create -g $RG -n frontend --environment $ENV \\
  --image $ACR.azurecr.io/agentic-rag-frontend:v1 \\
  --ingress external --target-port 80 \\
  --cpu 0.25 --memory 0.5Gi --min-replicas 2 --max-replicas 6 \\
  --user-assigned $ID_RES \\
  --env-vars API_UPSTREAM=http://<api-internal-fqdn>:80 \\
  --secrets api-key=keyvaultref:https://$KV.vault.azure.net/secrets/API-KEY,identityref:$ID_RES
# Map secret to env API_KEY. nginx envsubst runs at container start.
""",
            st,
        )
    )
    story.append(
        note(
            "Internal Container Apps ingress listens on port 80 even when the container target port is 8000. "
            "Set <font face='Courier'>API_UPSTREAM=http://api:80</font> (or the full internal FQDN with scheme http "
            "and no :8000) unless you use TCP ingress. Confirm with "
            "<font face='Courier'>az containerapp show -g $RG -n api --query properties.configuration.ingress</font>.",
            st,
            theme,
        )
    )

    story.append(p("Step 8 — Custom domain, TLS, and Front Door", st["step"]))
    story.append(
        numbered(
            [
                "On the frontend Container App: add hostname $APP_HOST, create the validation TXT/CNAME.",
                "Bind a managed certificate, or use a Key Vault certificate.",
                "Set CORS_ORIGINS and TRUSTED_HOSTS to https://$APP_HOST and update the API revision.",
                "Optional but recommended: Azure Front Door Premium in front of the frontend FQDN, WAF policy "
                "Detection then Prevention, origin timeout ≥ 240–300 seconds for SSE.",
                "After TLS is confirmed, uncomment HSTS in frontend/nginx.conf, rebuild, and deploy a new revision.",
            ],
            st,
        )
    )

    story.append(p("Step 9 — Ingest", st["step"]))
    story.append(
        p(
            "Create a Container Apps Job from the same API image (same files mount, same secrets):",
            st["body"],
        )
    )
    story.append(
        code_block(
            """
az containerapp job create -g $RG -n ingest-job --environment $ENV \\
  --image $ACR.azurecr.io/agentic-rag-api:v1 \\
  --cpu 2.0 --memory 4.0Gi --replica-timeout 1800 \\
  --command python --args -m src.ingestion.ingest --source /app/data/sample_docs

az containerapp job start -g $RG -n ingest-job

curl -sS https://$APP_HOST/api/health
# From an internal debug container, or temporarily:
curl -sS -H "X-API-Key: $API_KEY" https://$APP_HOST/api/health/ready
""",
            st,
        )
    )

    story.append(p("Step 10 — Monitoring", st["step"]))
    story.append(
        bullets(
            [
                "Container Apps system logs and console logs in the Log Analytics workspace.",
                "Alert rules: replica restart, 5xx on frontend ingress, Redis server load, Files throttling.",
                "Application Insights is optional; the API already emits Prometheus on /metrics.",
                "If you scrape metrics from a sidecar or Grafana agent on the environment, keep the API internal "
                "and set PROTECT_METRICS_ENDPOINT=false only for that private scrape path.",
                "LangSmith remains an external SaaS; store LANGSMITH_API_KEY in Key Vault.",
            ],
            st,
        )
    )

    story.append(p("Step 11 — CI/CD", st["step"]))
    story.append(
        p(
            "Keep the existing GitHub Actions quality workflow. Add a prod deploy job using "
            "<font face='Courier'>azure/login</font> with a federated credential (Entra app) — no client secret in GitHub:",
            st["body"],
        )
    )
    story.append(
        numbered(
            [
                "az acr build or docker buildx push SHA tags to ACR.",
                "az containerapp update --image ...:sha for api and frontend.",
                "Run ingest-job only when documents or chunking settings changed.",
                "Smoke GET /api/health and a canonical query through the public host.",
            ],
            st,
        )
    )

    story.append(p("6. Verification", st["h1"]))
    story.append(
        code_block(
            """
curl -i https://rag.example.com/api/health

curl -N https://rag.example.com/api/query/stream \\
  -H "Content-Type: application/json" \\
  -d '{"question":"What is Self-RAG?","mode":"canonical"}'

# Browser: https://rag.example.com — citations, upload PDF, thumbs feedback.
# Repeat a question and look for cache_hit (Redis).
""",
            st,
        )
    )

    story.append(p("7. Scaling, cost, and limits", st["h1"]))
    story.append(
        table(
            ["Knob", "Guidance"],
            [
                ["Frontend replicas", "Autoscale 2–6 on HTTP concurrency"],
                ["API replicas", "Stay at 1; BM25 and semantic cache are in-process"],
                ["Chroma replicas", "1. Files share is the durability layer"],
                ["Scale to zero", "Never on API or Chroma"],
                ["Front Door origin timeout", "Raise for SSE; default is too short for multi-hop"],
                ["CPU/memory API", "2 vCPU / 4Gi starting point; watch working set after ingest"],
            ],
            st,
            theme,
            widths=[48 * mm, None],
        )
    )
    story.append(
        p(
            "Cost shape: Container Apps (API 2 vCPU always-on) + Redis C1 + Files Premium + NAT + Front Door "
            "will usually be smaller than OpenAI token spend. Put a budget on the resource group and a cap "
            "on the OpenAI project. Azure OpenAI is an optional later swap for OPENAI_API_KEY / embeddings; "
            "it is not required to deploy this repo as-is.",
            st["body"],
        )
    )

    story.append(p("8. Simpler staging path (VM + Compose)", st["h1"]))
    story.append(
        p(
            "Create an Ubuntu 22.04 VM, install Docker, open 443 via NSG only from your IP or from an "
            "Application Gateway, clone the repo, and run the documented compose stack from "
            "<font face='Courier'>docs/PRODUCTION.md</font>. Point a DNS name at the VM or gateway. Use this "
            "only for staging; Redis and Chroma would be on the same disk without backups.",
            st["body"],
        )
    )

    story.append(p("9. Troubleshooting", st["h1"]))
    story.append(
        table(
            ["Symptom", "Likely cause", "Fix"],
            [
                ["Revision fails to start", "Production config check", "Log: API_KEY length, CORS=*, missing OPENAI"],
                ["UI 502 / 401", "API_UPSTREAM host/port wrong or API_KEY mismatch", "Internal ingress is port 80; one Key Vault secret"],
                ["Stream dies at ~60–120s", "Front Door / ingress timeout", "Raise origin and ACA request timeouts to 320s+"],
                ["Chroma empty after restart", "Files share not mounted", "Check volume in container app YAML"],
                ["Redis connection error", "SSL port 6380 / rediss:// and firewall", "Private endpoint + REDIS-URL secret"],
                ["Upload 413", "Ingress body limit vs nginx 25m", "Raise ACA max request body; INGEST_MAX_UPLOAD_MB"],
                ["Cold start 20s+", "API scaled to 0", "min-replicas=1"],
            ],
            st,
            theme,
            widths=[42 * mm, 55 * mm, None],
        )
    )

    story.append(p("10. Production checklist", st["h1"]))
    story.append(
        bullets(
            [
                "Key Vault + managed identity; no secrets in ACR images or GitHub variables.",
                "API and Chroma ingress internal. Redis public access disabled.",
                "CORS and TRUSTED_HOSTS match https://$APP_HOST.",
                "API and Chroma minReplicas=1. ALB/Front Door timeout ≥ 300s.",
                "Ingest job succeeded; /health/ready chroma ok.",
                "Log Analytics + alerts on 5xx and restarts.",
                "OpenAI project cap + MAX_TOKENS_PER_HOUR.",
                "File share snapshots and blob versioning on corpus.",
                "WAF in detection, then prevention. Budget on the resource group.",
                "Federated GitHub OIDC deploy; prod branch only.",
            ],
            st,
        )
    )
    story.append(
        p(
            "Related repo docs: <font face='Courier'>docs/PRODUCTION.md</font>, "
            "<font face='Courier'>docs/ARCHITECTURE.md</font>, <font face='Courier'>docs/GUARDRAILS.md</font>, "
            "<font face='Courier'>docs/API.md</font>.",
            st["caption"],
        )
    )
    return story


def build(theme: dict, builder):
    st = styles(theme)
    out = DOCS / theme["filename"]
    doc = SimpleDocTemplate(
        str(out),
        pagesize=PAGE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title=theme["title"],
        author="Agentic RAG",
        subject=theme["subtitle"],
    )
    extra = (
        "Recommended path on AWS is Amazon ECS on Fargate plus ElastiCache, EFS, and an ALB. "
        "A single EC2 + Docker Compose box is documented as staging only."
        if theme["name"] == "AWS"
        else "Recommended path on Azure is Azure Container Apps plus Azure Cache for Redis, Azure Files, "
        "and Key Vault. A single VM + Docker Compose box is documented as staging only."
    )
    story = []
    story.extend(cover(theme, st, extra))
    toc = [
        "1. What you are deploying",
        "2. Complete service catalog (required, recommended, optional)",
        "3. Recommended topology",
        "4. Prerequisites",
        "5. Step-by-step deployment",
        "6. Verification",
        "7. Scaling, cost, and limits",
        "8. Simpler staging path",
        "9. Troubleshooting",
        "10. Production checklist",
    ]
    for i, item in enumerate(toc, 1):
        story.append(p(f"{item}", st["toc"]))
    story.append(PageBreak())
    story.extend(app_context(st, theme))
    if theme["name"] == "AWS":
        story.extend(
            env_table(
                st,
                theme,
                "rediss://:${REDIS_AUTH}@rag-redis.cache.amazonaws.com:6379/0",
                "chroma.rag.local",
                "https://rag.example.com",
                "rag.example.com",
            )
        )
        story.extend(aws_steps(st, theme))
    else:
        story.extend(
            env_table(
                st,
                theme,
                "rediss://:${REDIS_KEY}@redis-rag-prod.redis.cache.windows.net:6380/0",
                "<chroma-internal-fqdn>",
                "https://rag.example.com",
                "rag.example.com",
            )
        )
        story.extend(azure_steps(st, theme))
    doc.build(
        story,
        onFirstPage=lambda c, d: add_header_footer(c, d, theme),
        onLaterPages=lambda c, d: add_header_footer(c, d, theme),
    )
    print(f"Wrote {out}")


if __name__ == "__main__":
    build(AWS, aws_steps)
    build(AZURE, azure_steps)

"""Tests for Fine-Grained Document RBAC & Multi-Tenancy Retrieval Filtering."""

from langchain_core.documents import Document

from src.retrieval.retriever import _filter_rbac
from src.schemas import RBACContext


def test_rbac_context_authorization_logic():
    # 1. Public user in default tenant
    public_ctx = RBACContext(tenant_id="default", user_roles=["public"])

    assert public_ctx.is_authorized(doc_tenant_id="default", doc_access_groups=["public"])
    assert public_ctx.is_authorized(doc_tenant_id="global", doc_access_groups=["public"])
    # Not authorized to other tenant
    assert not public_ctx.is_authorized(doc_tenant_id="tenant_b", doc_access_groups=["public"])
    # Not authorized to confidential admin group
    assert not public_ctx.is_authorized(doc_tenant_id="default", doc_access_groups=["admin", "finance"])

    # 2. Finance user in Tenant A
    finance_ctx = RBACContext(tenant_id="tenant_a", user_roles=["finance", "internal"])
    assert finance_ctx.is_authorized(doc_tenant_id="tenant_a", doc_access_groups=["finance"])
    assert finance_ctx.is_authorized(doc_tenant_id="tenant_a", doc_access_groups=["public"])
    assert not finance_ctx.is_authorized(doc_tenant_id="tenant_a", doc_access_groups=["legal"])
    assert not finance_ctx.is_authorized(doc_tenant_id="tenant_b", doc_access_groups=["finance"])

    # 3. Super Admin
    admin_ctx = RBACContext(tenant_id="tenant_a", user_roles=["admin"])
    assert admin_ctx.is_authorized(doc_tenant_id="tenant_a", doc_access_groups=["legal", "finance", "secret"])


def test_filter_rbac_filters_unauthorized_documents():
    docs = [
        Document(
            page_content="Public general knowledge",
            metadata={"tenant_id": "default", "access_groups": ["public"]},
        ),
        Document(
            page_content="Tenant A internal operations",
            metadata={"tenant_id": "tenant_a", "access_groups": ["internal"]},
        ),
        Document(
            page_content="Tenant A executive payroll",
            metadata={"tenant_id": "tenant_a", "access_groups": ["admin", "executive"]},
        ),
        Document(
            page_content="Tenant B secrets",
            metadata={"tenant_id": "tenant_b", "access_groups": ["admin"]},
        ),
    ]

    # Context 1: Public Default User
    ctx_public = RBACContext(tenant_id="default", user_roles=["public"])
    filtered_public = _filter_rbac(docs, ctx_public)
    assert len(filtered_public) == 1
    assert "Public general knowledge" in filtered_public[0].page_content

    # Context 2: Tenant A Employee (internal)
    ctx_employee = RBACContext(tenant_id="tenant_a", user_roles=["internal"])
    filtered_employee = _filter_rbac(docs, ctx_employee)
    assert len(filtered_employee) == 1
    assert "Tenant A internal operations" in filtered_employee[0].page_content

    # Context 3: Tenant A Executive
    ctx_exec = RBACContext(tenant_id="tenant_a", user_roles=["internal", "executive"])
    filtered_exec = _filter_rbac(docs, ctx_exec)
    assert len(filtered_exec) == 2
    contents = [d.page_content for d in filtered_exec]
    assert "Tenant A internal operations" in contents
    assert "Tenant A executive payroll" in contents
    assert not any("Tenant B" in c for c in contents)

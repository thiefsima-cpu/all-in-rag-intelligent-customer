"""Customer-service domain pack."""

from ..contracts import (
    CitationProjection,
    DomainBuildDataView,
    DomainOntology,
    DomainPack,
    DomainQueryConstraintSchema,
    DomainReasoningVocabulary,
    GraphNodeType,
    GraphRelationType,
)
from .documents import CustomerServiceDocumentMapper

_POLICY_LABELS = (
    "RefundPolicy",
    "WarrantyPolicy",
    "InvoicePolicy",
    "ServicePolicy",
)
_REFERENCE_SOURCE_LABELS = (*_POLICY_LABELS, "Product", "SupportArticle")

CUSTOMER_SERVICE_ONTOLOGY = DomainOntology(
    primary_labels=(
        "Order",
        "Product",
        "RefundPolicy",
        "WarrantyPolicy",
        "InvoicePolicy",
        "ServicePolicy",
        "SupportArticle",
    ),
    node_types=(
        GraphNodeType(
            "Order",
            ("order_id", "orderId", "nodeId", "id"),
            ("title", "order_id", "orderId"),
        ),
        GraphNodeType(
            "Product",
            ("product_sku", "sku", "nodeId", "id"),
            ("title", "name", "product_sku", "sku"),
        ),
        GraphNodeType(
            "RefundPolicy",
            ("policy_id", "policyId", "nodeId", "id"),
            ("title", "name"),
            ("version", "product_sku"),
        ),
        GraphNodeType(
            "WarrantyPolicy",
            ("policy_id", "policyId", "nodeId", "id"),
            ("title", "name"),
            ("version", "product_sku"),
        ),
        GraphNodeType(
            "InvoicePolicy",
            ("policy_id", "policyId", "nodeId", "id"),
            ("title", "name"),
            ("version",),
        ),
        GraphNodeType(
            "ServicePolicy",
            ("policy_id", "policyId", "nodeId", "id"),
            ("title", "name"),
            ("version", "product_sku"),
        ),
        GraphNodeType("PolicyTerm", ("id", "nodeId"), ("name", "title")),
        GraphNodeType(
            "SupportArticle",
            ("article_id", "articleId", "nodeId", "id"),
            ("title", "name"),
        ),
    ),
    relation_types=(
        GraphRelationType("GOVERNED_BY", ("Order",), ("ServicePolicy", "RefundPolicy")),
        GraphRelationType("APPLIES_TO", (*_POLICY_LABELS, "SupportArticle"), ("Product",)),
        GraphRelationType("CONTAINS_PRODUCT", ("Order",), ("Product",)),
        GraphRelationType("HAS_REFUND_RULE", ("ServicePolicy",), ("RefundPolicy",)),
        GraphRelationType("HAS_WARRANTY_TERM", ("Product",), ("WarrantyPolicy",)),
        GraphRelationType("HAS_INVOICE_RULE", ("ServicePolicy",), ("InvoicePolicy",)),
        GraphRelationType("DESCRIBES_ORDER", _REFERENCE_SOURCE_LABELS, ("Order",)),
        GraphRelationType("REFERENCES_POLICY", _REFERENCE_SOURCE_LABELS, _POLICY_LABELS),
        GraphRelationType("HAS_TERM", _POLICY_LABELS, ("PolicyTerm",)),
        GraphRelationType("SUPERSEDES", _POLICY_LABELS, _POLICY_LABELS),
        GraphRelationType("CONFLICTS_WITH", _POLICY_LABELS, _POLICY_LABELS),
        GraphRelationType("HAS_STATUS", ("Order",), ("SupportArticle",)),
    ),
)

CUSTOMER_SERVICE_DOMAIN_PACK = DomainPack(
    name="customer_service",
    version="customer-service-domain-v1",
    ontology=CUSTOMER_SERVICE_ONTOLOGY,
    document_mapper=CustomerServiceDocumentMapper(),
    query_policy_bundle="customer-service-v1",
    vector_collection_name="customer_service_knowledge",
    citation_projection=CitationProjection(
        citation_label="客服证据",
        public_attribute_keys=(
            "document_type",
            "status",
            "policy_id",
            "product_sku",
            "effective_from",
            "effective_to",
            "version",
        ),
        expose_content=False,
        expose_entity_identity=False,
        expose_matched_terms=False,
    ),
    evaluation_resource="evaluation.json",
    query_constraints=DomainQueryConstraintSchema(),
    reasoning_vocabulary=DomainReasoningVocabulary(
        subject_fallback="the target customer-service entities",
        comparison_labels=(
            "Order",
            "Product",
            "RefundPolicy",
            "WarrantyPolicy",
            "InvoicePolicy",
            "ServicePolicy",
            "SupportArticle",
        ),
        compositional_labels=(
            ("Product", "products"),
            ("PolicyTerm", "policy terms"),
            ("SupportArticle", "support articles"),
        ),
        semantic_effect_label="policy effects",
        constraint_labels=(
            ("RefundPolicy", "refund policies"),
            ("WarrantyPolicy", "warranty policies"),
            ("InvoicePolicy", "invoice policies"),
        ),
    ),
    build_data_view=DomainBuildDataView(primary_group="entities"),
    graph_import_resource="customer_service_seed.cypher",
)
DOMAIN_PACK = CUSTOMER_SERVICE_DOMAIN_PACK

__all__ = [
    "CUSTOMER_SERVICE_DOMAIN_PACK",
    "CUSTOMER_SERVICE_ONTOLOGY",
    "CustomerServiceDocumentMapper",
    "DOMAIN_PACK",
]

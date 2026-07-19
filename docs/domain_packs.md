# Domain packs

GraphRAG C9 separates reusable RAG orchestration from business-domain behavior through a
versioned `DomainPack` contract. The selected pack owns all knowledge assumptions that should not
leak into retrieval, generation, or the public API core.

## Contract

`rag_modules/domains/contracts.py` defines the pack boundary:

- `DomainOntology`: primary Neo4j labels, node identity fields, and allowed relationships;
- `DomainDocumentMapper`: record-to-document mapping plus deterministic entity/relation extraction;
- `query_policy_bundle`: the domain query policy and prompt bundle;
- `CitationProjection`: the public citation label and allowlisted public attributes;
- `evaluation_resource`: a packaged, reproducible domain evaluation set.

Each domain package exports `DOMAIN_PACK`. The domain registry registers those packs and
application composition injects the selected graph loader, document mapper, query policy, graph
labels, relation types, and citation projection into the otherwise domain-neutral runtime.

## Customer-service pack

`rag_modules/domains/customer_service/` is the production domain. Its ontology includes orders,
products, refund policies, warranty policies, invoice policies, service policies, and support
articles. It models relationships including `GOVERNED_BY`, `APPLIES_TO`, `HAS_WARRANTY_TERM`,
`SUPERSEDES`, and `CONFLICTS_WITH`.

The packaged evaluation resource contains grounded positive cases for:

- order status with an update timestamp;
- refund eligibility and effective date;
- product warranty duration;
- invoice-title correction procedure;
- current-versus-superseded policy versions.

It also retains an identifier-missing clarification control. These cases prove both grounded
answering and safe abstention; they do not treat abstention alone as evidence of domain ability.

The Docker bootstrap loads `cypher/customer_service_seed.cypher`, then builds BM25, graph KV, and
Milvus artifacts from the customer documents. The seed is intentionally small and reviewable. A
production deployment should replace it with governed customer knowledge ingestion and must not
commit customer records or credentials.

## Selecting a domain

The `dev`, `eval_fast`, and `eval_quality` profiles select customer service:

```toml
[domain]
name = "customer_service"
```

The selected pack supplies `customer-service-v1`; profiles do not repeat that mapping. For an
explicit environment override:

```dotenv
GRAPH_RAG_DOMAIN=customer_service
MILVUS_COLLECTION_NAME=customer_service_knowledge
```

To run the compatibility recipe pack, set `GRAPH_RAG_DOMAIN=recipe`; the pack supplies
`c9-default-v1`. Then rebuild artifacts into a separate Milvus collection. Never reuse a ready
artifact manifest or collection across domains. `QUERY_POLICY_BUNDLE` remains available only for
an intentional, domain-compatible custom policy override.

## Graph record shape

Customer graph nodes should carry:

- `nodeId`: stable entity identifier;
- `domain: "customer_service"`;
- `document_type`: one of `order`, `product`, `refund_policy`, `warranty_policy`,
  `invoice_policy`, `service_policy`, or `support_article`;
- `title` or `name` and a grounded `content` field;
- only applicable public attributes such as `status`, `policy_id`, `product_sku`, `version`,
  `effective_from`, `effective_to`, `source_uri`, or `updated_at`.

The mapper copies only the citation allowlist into the public `attributes` projection. Customer
service public citations omit raw evidence content, entity identifiers, entity names, and matched
terms; those fields remain available only on the authenticated debug surface. Recipe citations
retain the legacy `recipe_name` field for compatibility.

Citation redaction is defense in depth, not row-level authorization. Production deployments must
keep API authentication enabled and enforce tenant/customer ownership before retrieval and answer
generation. This repository does not invent an ownership rule for deployments that have not
provided an identity-to-record contract.

## Adding another domain

Add a package under `rag_modules/domains/<name>/`, define its ontology, mapper/extractor,
projection, prompt bundle, and grounded evaluation resource, export it as `DOMAIN_PACK`, and
register it with `register_domain_pack` during application composition. No central selector or
configuration `Literal` needs updating. Add focused tests that prove
positive grounded answers, citation projection, domain selection, graph identity, and that the
prompt does not inherit concepts from another domain.

# Domain packs

GraphRAG C9 separates reusable RAG orchestration from business-domain behavior through a
versioned `DomainPack` contract. The selected pack owns all knowledge assumptions that should not
leak into retrieval, generation, or the public API core.

## Contract

`rag_modules/domains/contracts.py` defines the pack boundary:

- `DomainOntology`: primary Neo4j labels, node identity fields, and allowed relationships;
- `DomainDocumentMapper`: record-to-document mapping plus deterministic entity/relation extraction;
- `DomainQueryConstraintSchema`: domain extension fields and their policy term groups;
- `DomainReasoningVocabulary`: labels and copy used to explain domain graph reasoning;
- `DomainBuildDataView`: primary/related entity groups and domain metric projections;
- build loader/document-builder factories for domain-specific materialization;
- an optional graph-import resource plus path rewrites for bootstrap data;
- an optional semantic-graph writer factory for domain-derived nodes and relationships;
- `query_policy_bundle`: the domain query policy and prompt bundle;
- `CitationProjection`: the public citation label and allowlisted public attributes;
- `evaluation_resource`: a packaged, reproducible domain evaluation set.

Each domain package exports `DOMAIN_PACK`. The domain registry registers those packs and
application composition injects the selected graph loader, document mapper, query policy, graph
labels, relation types, constraint matcher, reasoning vocabulary, build data view, and citation
projection into the otherwise domain-neutral runtime.

Bootstrap and gate scripts resolve the selected pack as well. Graph import resources, legacy
domainless-label allowances, smoke-corpus domain selection, and entity hit-rate report fields are
data/configuration owned; shared scripts do not branch on recipe labels or expose recipe-named
evaluation DTOs.

Graph cache warmup, entity linking, fallback retrieval, graph indexing, and vector persistence use
that injected ontology. Generic indexes persist entity identity and an opaque `attributes` object;
they do not reserve physical fields or query branches for a particular business domain.

The core query contract contains only `entity_terms`, `excluded_entity_terms`, `relation_types`,
`temporal_filters`, `structured_filters`, and an opaque `extension` object. The selected pack is
the only component allowed to define names inside that extension. Recipe fields such as
ingredients, cuisine, health preferences, and preparation time therefore live in the recipe pack,
not in `rag_modules/contracts` or query-understanding DTOs.

Build orchestration follows the same rule. The generic graph-preparation package owns state,
chunking, ontology loading, and generic statistics. A pack may supply its own loader and document
builder factories; the recipe implementations and their ingredient/step input types live under
`rag_modules/domains/recipe/build/`. Generic load results expose entity groups, while
`DomainBuildDataView` projects optional domain metrics such as recipe counts only for that pack.

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

The canonical live-quality gate is also customer-service-only: all 18 cases select
`customer_service`, with five grounded answers and thirteen abstention, clarification, or
constraint-conflict controls. Recipe quality cases remain part of the optional recipe domain's
offline resources rather than the production live gate.

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

The configuration model uses the same `customer_service` default, so omitting a profile or
environment override cannot silently select the compatibility recipe domain.

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
terms; those fields remain available only on the authenticated debug surface. Public evidence
uses only the generic `entity_id`, `entity_name`, and `entity_type` identity fields. The former
recipe-specific aliases are not part of either the core or public response contract.

Citation redaction is defense in depth, not row-level authorization. Production deployments must
keep API authentication enabled and enforce tenant/customer ownership before retrieval and answer
generation. This repository does not invent an ownership rule for deployments that have not
provided an identity-to-record contract.

## Adding another domain

Add a package under `rag_modules/domains/<name>/`, define its ontology, mapper/extractor,
constraint extension, reasoning vocabulary, build data view, projection, prompt bundle, and
grounded evaluation resource. Add a graph-import resource only when the domain ships bootstrap
data, and supply build factories only when the ontology-driven defaults are insufficient. Export
the pack as `DOMAIN_PACK` and register it with `register_domain_pack` during application
composition. No central selector or configuration `Literal` needs updating. Add focused tests
that prove positive grounded answers, citation projection, domain selection, graph identity,
build metrics, and that the prompt and core DTOs do not inherit concepts from another domain.

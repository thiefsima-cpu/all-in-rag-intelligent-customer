// Minimal, reviewable customer-service graph used by the Docker development profile.
// Production deployments should replace this seed through their governed ingestion path.

CREATE CONSTRAINT customer_order_node_id IF NOT EXISTS
FOR (n:Order) REQUIRE n.nodeId IS UNIQUE;

CREATE CONSTRAINT customer_product_node_id IF NOT EXISTS
FOR (n:Product) REQUIRE n.nodeId IS UNIQUE;

CREATE CONSTRAINT customer_policy_node_id IF NOT EXISTS
FOR (n:ServicePolicy) REQUIRE n.nodeId IS UNIQUE;

CREATE CONSTRAINT customer_article_node_id IF NOT EXISTS
FOR (n:SupportArticle) REQUIRE n.nodeId IS UNIQUE;

MERGE (order:Order {nodeId: 'CS-1001'})
SET order.domain = 'customer_service',
    order.order_id = 'CS-1001',
    order.title = '订单 CS-1001',
    order.document_type = 'order',
    order.status = '已发货',
    order.updated_at = '2026-07-17T16:20:00+08:00',
    order.content = '订单 CS-1001 已发货，状态更新时间为 2026-07-17 16:20。';

MERGE (product:Product {nodeId: 'SKU-PHONE-A'})
SET product.domain = 'customer_service',
    product.product_sku = 'SKU-PHONE-A',
    product.title = '商品 SKU-PHONE-A',
    product.document_type = 'product',
    product.content = 'SKU-PHONE-A 是适用七天无理由退货和两年有限保修的手机商品。';

MERGE (refundCurrent:ServicePolicy:RefundPolicy {nodeId: 'POL-REFUND-2026-07'})
SET refundCurrent.domain = 'customer_service',
    refundCurrent.policy_id = 'POL-REFUND-2026-07',
    refundCurrent.title = '七天无理由退货政策',
    refundCurrent.document_type = 'refund_policy',
    refundCurrent.product_sku = 'SKU-PHONE-A',
    refundCurrent.version = '2026.07',
    refundCurrent.effective_from = '2026-07-01',
    refundCurrent.supersedes = 'POL-REFUND-2026-06',
    refundCurrent.content = '自 2026-07-01 起，适用商品在签收后 7 天内且保持未拆封状态，可以申请无理由退货。退款政策 2026.07 已替代 2026.06 版本。';

MERGE (refundPrevious:ServicePolicy:RefundPolicy {nodeId: 'POL-REFUND-2026-06'})
SET refundPrevious.domain = 'customer_service',
    refundPrevious.policy_id = 'POL-REFUND-2026-06',
    refundPrevious.title = '退款政策 2026.06（已失效）',
    refundPrevious.document_type = 'refund_policy',
    refundPrevious.version = '2026.06',
    refundPrevious.effective_to = '2026-06-30',
    refundPrevious.content = '退款政策 2026.06 已于 2026-06-30 失效，由 2026.07 版本替代。';

MERGE (warranty:ServicePolicy:WarrantyPolicy {nodeId: 'POL-WARRANTY-A-2026'})
SET warranty.domain = 'customer_service',
    warranty.policy_id = 'POL-WARRANTY-A-2026',
    warranty.title = '手机 A 保修政策',
    warranty.document_type = 'warranty_policy',
    warranty.product_sku = 'SKU-PHONE-A',
    warranty.effective_from = '2026-01-01',
    warranty.version = '2026.01',
    warranty.content = '商品 SKU-PHONE-A 自购买日起享有 2 年有限保修。';

MERGE (invoice:ServicePolicy:InvoicePolicy {nodeId: 'POL-INVOICE-2026-03'})
SET invoice.domain = 'customer_service',
    invoice.policy_id = 'POL-INVOICE-2026-03',
    invoice.title = '电子发票更正规则',
    invoice.document_type = 'invoice_policy',
    invoice.effective_from = '2026-03-15',
    invoice.version = '2026.03',
    invoice.content = '电子发票开具后不能直接修改抬头；核验订单信息后，应先红冲原发票再重新开具。';

MERGE (statusArticle:SupportArticle {nodeId: 'ARTICLE-ORDER-STATUS'})
SET statusArticle.domain = 'customer_service',
    statusArticle.article_id = 'ARTICLE-ORDER-STATUS',
    statusArticle.title = '订单状态说明',
    statusArticle.document_type = 'support_article',
    statusArticle.content = '已发货表示商品已经交由承运方，具体送达时间以物流轨迹为准。';

MATCH (order:Order {nodeId: 'CS-1001'})
MATCH (refundCurrent:ServicePolicy {nodeId: 'POL-REFUND-2026-07'})
MATCH (product:Product {nodeId: 'SKU-PHONE-A'})
MATCH (warranty:ServicePolicy {nodeId: 'POL-WARRANTY-A-2026'})
MATCH (invoice:ServicePolicy {nodeId: 'POL-INVOICE-2026-03'})
MATCH (statusArticle:SupportArticle {nodeId: 'ARTICLE-ORDER-STATUS'})
MERGE (order)-[:GOVERNED_BY]->(refundCurrent)
MERGE (order)-[:HAS_STATUS]->(statusArticle)
MERGE (refundCurrent)-[:APPLIES_TO]->(product)
MERGE (product)-[:HAS_WARRANTY_TERM]->(warranty)
MERGE (refundCurrent)-[:HAS_INVOICE_RULE]->(invoice);

MATCH (refundCurrent:ServicePolicy {nodeId: 'POL-REFUND-2026-07'})
MATCH (refundPrevious:ServicePolicy {nodeId: 'POL-REFUND-2026-06'})
MERGE (refundCurrent)-[:SUPERSEDES]->(refundPrevious);

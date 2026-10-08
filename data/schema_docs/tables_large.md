# Esquema sintético ampliado: comercio, logística, facturación y cobranza

Este documento describe el esquema de `db/schema_large.sql`. Cada bloque de
tabla está pensado para convertirse más adelante en un fragmento semántico;
las relaciones indicadas son reales y están declaradas como foreign keys.

## Tabla: regions
Catálogo de regiones comerciales y logísticas. Columnas: region_id (PK),
region_name, country. Una región tiene representantes de ventas y bodegas.

## Tabla: sales_representatives
Representantes comerciales. Columnas: sales_rep_id (PK), region_id (FK a
regions), full_name, email, hired_at. Un representante puede atender muchos
clientes y registrar muchos pedidos.

## Tabla: customer_segments
Segmentos comerciales de cliente. Columnas: segment_id (PK), segment_name,
credit_limit. Cada cliente pertenece a un segmento.

## Tabla: customers
Clientes que hacen pedidos y reciben facturas. Columnas: customer_id (PK),
segment_id (FK a customer_segments), sales_rep_id (FK a sales_representatives),
full_name, email, created_at. Tiene direcciones, contactos, pedidos y facturas.

## Tabla: customer_addresses
Direcciones de facturación o envío de un cliente. Columnas: address_id (PK),
customer_id (FK a customers), address_type, street, city, country, is_default.
Un pedido puede usar una dirección de envío concreta.

## Tabla: customer_contacts
Personas de contacto de un cliente. Columnas: contact_id (PK), customer_id
(FK a customers), full_name, role_name, email, phone, is_primary. No representa
una dirección ni un representante de ventas.

## Tabla: product_categories
Categorías jerárquicas de productos. Columnas: category_id (PK),
parent_category_id (FK autoreferenciada a product_categories), category_name.
Una categoría puede tener subcategorías y productos.

## Tabla: products
Catálogo de productos vendibles. Columnas: product_id (PK), category_id (FK a
product_categories), sku, product_name, unit_price, active. Aparece en líneas
de pedido, líneas de factura e inventario.

## Tabla: warehouses
Bodegas desde las que se despachan pedidos. Columnas: warehouse_id (PK),
region_id (FK a regions), warehouse_name, city. Tiene registros de inventario
y participa en envíos.

## Tabla: inventory
Existencias de cada producto en una bodega. Clave primaria compuesta:
warehouse_id (FK a warehouses) + product_id (FK a products). También contiene
quantity_on_hand y reorder_point. No se conecta directamente a una orden.

## Tabla: orders
Cabecera de pedidos de clientes. Columnas: order_id (PK), customer_id (FK a
customers), sales_rep_id (FK a sales_representatives), shipping_address_id
(FK a customer_addresses), ordered_at, status. Tiene líneas, envíos y factura.

## Tabla: order_items
Líneas de un pedido. Columnas: order_item_id (PK), order_id (FK a orders),
product_id (FK a products), quantity, unit_price. Puede aparecer en un envío
y en una factura.

## Tabla: shipments
Despachos de pedidos. Columnas: shipment_id (PK), order_id (FK a orders),
warehouse_id (FK a warehouses), shipped_at, delivered_at, status. Un envío
puede contener varias líneas despachadas.

## Tabla: shipment_items
Detalle de líneas incluidas en un despacho. Columnas: shipment_item_id (PK),
shipment_id (FK a shipments), order_item_id (FK a order_items), quantity_shipped.
Es el vínculo entre los envíos y los productos solicitados.

## Tabla: invoices
Facturas emitidas por pedidos. Columnas: invoice_id (PK), order_id (FK a
orders), customer_id (FK a customers), issued_date, due_date, status,
total_amount. Una factura tiene líneas, pagos, acciones de cobranza y notas de
crédito.

## Tabla: invoice_items
Líneas facturadas. Columnas: invoice_item_id (PK), invoice_id (FK a invoices),
order_item_id (FK a order_items), product_id (FK a products), quantity,
line_amount. Permite relacionar facturación con el producto y la línea original.

## Tabla: payment_methods
Catálogo de medios de pago. Columnas: payment_method_id (PK), method_name,
provider_name. Un medio de pago puede usarse en varios pagos.

## Tabla: payments
Pagos realizados contra facturas. Columnas: payment_id (PK), invoice_id (FK a
invoices), payment_method_id (FK a payment_methods), amount_paid, paid_at,
payment_reference. Una factura puede recibir pagos parciales.

## Tabla: collection_actions
Gestiones de cobranza sobre facturas. Columnas: action_id (PK), invoice_id
(FK a invoices), action_type, action_date, notes. Incluye recordatorios,
llamadas y negociaciones.

## Tabla: credit_notes
Notas de crédito emitidas para una factura. Columnas: credit_note_id (PK),
invoice_id (FK a invoices), issued_date, amount, reason. No es un pago: reduce
el importe facturado por un motivo comercial.

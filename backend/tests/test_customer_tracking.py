from fastapi.testclient import TestClient
from app.main import app
from app.models import Order, Customer, Article

def test_customer_tracking_endpoint_returns_safe_data(db, client, headers):
    customer = Customer(name="Buyer Tracking Test")
    db.add(customer)
    db.flush()

    order = Order(
        order_id="SO-TEST-TRACK-001",
        buyer=customer.name,
        customer_id=customer.id,
        order_type="SAMPLE_PRODUCTION",
        overall_status="ACTIVE",
        finance_status="PAID",
        finance_gate_status="APPROVED",
        shipment_status="READY",
    )
    art = Article(article_code="ART-01", qty=200, production_status="IN_PROCESS")
    order.articles.append(art)
    db.add(order)
    db.commit()

    res = client.get("/api/orders/SO-TEST-TRACK-001/customer-tracking", headers=headers("CMO_SUPPORT"))
    assert res.status_code == 200
    data = res.json()
    assert data["order_id"] == "SO-TEST-TRACK-001"
    assert data["status_pembayaran_sederhana"] == "Pembayaran lunas"
    assert data["shipment"] == "Pesanan siap dikirim"
    assert data["tahap"] == "Pesanan siap dikirim"
    assert "hpp" not in data
    assert "margin" not in data
    assert "harga_supplier" not in data

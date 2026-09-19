from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field, model_validator, ConfigDict
from .models import Role, OrderType

class LoginRequest(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: Role
    class Config:
        from_attributes = True

class ArticleCreate(BaseModel):
    article_code: str
    garment_type: Optional[str] = None
    qty: int = Field(gt=0)
    size_breakdown: Optional[str] = None
    sample_required: bool = False
    production_route: Optional[str] = None

class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buyer: str = Field(min_length=1, max_length=160)
    customer_id: Optional[int] = None
    order_type: OrderType
    buyer_deadline: Optional[date] = None
    notes: Optional[str] = None
    articles: List[ArticleCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_articles(self):
        self.buyer = self.buyer.strip()
        if not self.buyer:
            raise ValueError("Buyer is required")
        codes = [a.article_code.strip() for a in self.articles]
        if any(not c for c in codes) or len(set(codes)) != len(codes):
            raise ValueError("Article codes must be nonempty and unique within the order")
        for article, code in zip(self.articles, codes):
            article.article_code = code
        if self.order_type in (OrderType.SAMPLE_ONLY, OrderType.SAMPLE_PRODUCTION):
            if not any(a.sample_required for a in self.articles):
                for article in self.articles:
                    article.sample_required = True
        return self

class ArticleOut(BaseModel):
    id: int
    article_code: str
    garment_type: Optional[str]
    qty: int
    size_breakdown: Optional[str]
    sample_required: bool
    sample_status: str
    production_route: Optional[str]
    production_status: str
    class Config:
        from_attributes = True

class OrderOut(BaseModel):
    id: int
    order_id: str
    buyer: str
    order_type: OrderType
    order_date: date
    buyer_deadline: Optional[date]
    finance_status: str
    customer_id: Optional[int] = None
    finance_gate_status: str = "PENDING"
    finance_gate_notes: Optional[str] = None
    finance_term_kind: Optional[str] = None
    required_dp_amount: Optional[float] = None
    payment_evidence_ref: Optional[str] = None
    credit_due_date: Optional[date] = None
    material_status: str
    shipment_status: str
    customer_close_status: str
    operational_close_status: str
    financial_close_status: str
    overall_status: str
    flow_step: str = "ORDER"
    projected_shipment: Optional[date]
    buffer_days: Optional[int]
    notes: Optional[str]
    articles: List[ArticleOut] = []
    created_by_id: Optional[int] = None
    created_at: Optional[datetime] = None
    # Blueprint poin 3 mewajibkan `updated_at` di setiap baris antrean. Kolomnya
    # sudah ada di DB (`orders.updated_at`, non-null) — sebelumnya hanya tidak
    # ikut diserialisasi, sehingga kolom "Updated at" di OrderList selalu "—".
    updated_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class MovementOut(BaseModel):
    process: str
    qty_in: int
    qty_done: int
    qty_reject: int
    status: str
    pic_name: Optional[str]
    target_date: Optional[date]
    updated_at: datetime
    class Config:
        from_attributes = True

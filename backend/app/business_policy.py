"""CEO-owned business thresholds. No implicit financial thresholds are invented."""
import json
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict, model_validator
from fastapi import HTTPException
from .models import SystemConfig


class BusinessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minimum_margin_percent: Decimal = Field(ge=0, le=100)
    # DP minimum dalam Rupiah (permintaan pemilik 16 Okt 2026), bukan persen.
    minimum_dp_amount: Decimal = Field(ge=0)
    cfo_quotation_limit: Decimal = Field(gt=0)
    allow_credit_terms: bool = False

    @model_validator(mode="before")
    @classmethod
    def read_legacy_percent(cls, data):
        """Kebijakan lama menyimpan `minimum_dp_percent`. Persen tidak bisa diubah ke Rupiah tanpa
        menebak, jadi nilainya dibuang dan DP minimum menjadi Rp 0 sampai CEO mengisinya ulang."""
        if isinstance(data, dict) and "minimum_dp_percent" in data:
            data = {k: v for k, v in data.items() if k != "minimum_dp_percent"}
            data.setdefault("minimum_dp_amount", 0)
        return data


def get_policy(db):
    record = db.query(SystemConfig).filter_by(key="business_policy").first()
    if not record:
        raise HTTPException(409, "CEO must configure pricing and payment policy before approval")
    return BusinessPolicy.model_validate(json.loads(record.value))

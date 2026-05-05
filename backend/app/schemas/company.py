from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class CompanyBase(BaseModel):
    ticker: str
    name: Optional[str] = None
    cik: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None


class CompanyCreate(CompanyBase):
    pass


class CompanyResponse(CompanyBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

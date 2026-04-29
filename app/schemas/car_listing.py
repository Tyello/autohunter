from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from typing import Optional
from uuid import UUID
from datetime import datetime


class CarListingOut(BaseModel):
    id: UUID
    source: str
    title: Optional[str]
    price: Optional[float]
    currency: Optional[str]
    thumbnail_url: Optional[str]
    listing_url: Optional[str] = Field(default=None, validation_alias=AliasChoices("url", "listing_url"))
    location: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

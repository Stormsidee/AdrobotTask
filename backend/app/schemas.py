from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints

PositiveId = Annotated[int, Field(gt=0)]
CampaignName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=65)
]


def normalize_country(value):
    return value.strip().upper() if isinstance(value, str) else value


class CreateCampaign(BaseModel):
    name: CampaignName
    country: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$"), BeforeValidator(normalize_country)]
    offer_id: PositiveId
    domain_id: PositiveId | None = None
    group_id: PositiveId
    source_id: PositiveId | None = None


class AddOffer(BaseModel):
    offer_id: PositiveId

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from src.constants.enums import Review

class Request(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

class Credentials(Request):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)

class Upload(Request):
    name: str = Field(min_length=1, max_length=120)
    filename: str = Field(min_length=1, max_length=160)
    csv_text: str = Field(min_length=1, max_length=2_000_000)

class RunRequest(Request):
    dataset_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=120)
    params: dict = Field(default_factory=dict)

class ReviewRequest(Request):
    review: Review
    note: str = Field(min_length=1, max_length=500)
    decision: str = Field(default='', max_length=120)

class ScheduleRequest(RunRequest):
    recipient: str = Field(min_length=1, max_length=100)
    first_at: datetime
    repeat_daily: bool = False

class MergeRequest(Request):
    name: str = Field(min_length=1, max_length=120)
    rooms: list[str] = Field(min_length=1, max_length=50)
    params: dict = Field(default_factory=dict)

class MergePackageRequest(Request):
    room: str = Field(min_length=1, max_length=80)
    version: int = Field(ge=1, le=1_000_000)
    reference: str = Field(min_length=1, max_length=120)
    positive_count: int = Field(ge=0, le=5000)
    negative_count: int = Field(ge=0, le=5000)
    pattern_hits: dict[str, dict] = Field(default_factory=dict)
    credentials: list[str] = Field(default_factory=list, max_length=5000)
    params: dict | None = None
    note: str | None = Field(default=None, max_length=500)

class MergeReturnRequest(Request):
    room: str = Field(min_length=1, max_length=80)
    note: str = Field(min_length=1, max_length=500)

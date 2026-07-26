"""Skema saran/masukan pengguna."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FeedbackCategory = Literal["saran", "masalah", "lainnya"]
FeedbackStatus = Literal["baru", "ditinjau", "selesai"]


class FeedbackCreate(BaseModel):
    category: FeedbackCategory = "saran"
    message: str = Field(min_length=5, max_length=2000)


class FeedbackStatusUpdate(BaseModel):
    status: FeedbackStatus


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: dt.datetime
    user_id: int
    user_name: str
    user_role: str
    category: str
    message: str
    status: str

"""Skema notifikasi in-app."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: dt.datetime
    type: str
    title: str
    body: str
    link: str | None
    read: bool

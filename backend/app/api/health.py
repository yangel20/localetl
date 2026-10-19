from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.db import get_engine

router = APIRouter(tags=["system"])


class Health(BaseModel):
    status: Literal["ok"]
    database: Literal["ok", "unavailable"]


@router.get("/health", operation_id="getHealth", response_model=Health)
def get_health(engine: sa.Engine = Depends(get_engine)) -> Health:
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
        return Health(status="ok", database="ok")
    except sa.exc.SQLAlchemyError:
        return Health(status="ok", database="unavailable")

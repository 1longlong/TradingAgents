"""FR-TRD-001..006, ADR-001-simulated-trading-system.md: public input only."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

DecimalText = Annotated[StrictStr, Field(pattern=r"^\d{1,12}(?:\.\d{1,6})?$", max_length=20)]
RequestId = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")]
AccountId = Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{32}$")]


class SimulationError(ValueError):
    """Safe public simulation conflict, without paths or provider detail."""


class SimulationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AccountInput(SimulationInput):
    initial_cash: DecimalText = "100000.00"
    confirm: Literal["INITIALIZE", "RESET"]
    expected_version: StrictInt | None = Field(default=None, ge=0)
    expected_account_id: AccountId | None = None


class SimulationDecisionInput(SimulationInput):
    client_request_id: RequestId
    artifact_id: Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{16}$")]
    quote_price: DecimalText
    quote_as_of: StrictStr = Field(min_length=20, max_length=40)
    expected_version: StrictInt = Field(ge=0)
    expected_account_id: AccountId


class SimulationApprovalInput(SimulationInput):
    approved: bool
    approver: StrictStr = Field(min_length=1, max_length=120)
    reason: StrictStr = Field(min_length=1, max_length=1000)
    expected_version: StrictInt = Field(ge=0)
    expected_account_id: AccountId


class ScenarioRow(SimulationInput):
    date: StrictStr = Field(min_length=10, max_length=10)
    action: Literal["BUY", "SELL", "HOLD", "REVIEW"]
    price: DecimalText


class SimulationJobInput(SimulationInput):
    source: Literal["scenario", "research"] = "scenario"
    symbol: StrictStr = Field(min_length=1, max_length=32)
    start: StrictStr = Field(min_length=10, max_length=10)
    end: StrictStr = Field(min_length=10, max_length=10)
    initial_cash: DecimalText = "10000.00"
    rows: list[ScenarioRow] = Field(default_factory=list, max_length=366)
    resume_id: Annotated[StrictStr, Field(pattern=r"^sim_[a-f0-9]{12}$")] | None = None

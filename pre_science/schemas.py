"""JSON contracts shared by orchestration and isolated executors."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator
import json


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ExperimentRequest(Model):
    experiment_id: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=200_000)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    random_seed: int = Field(default=0, ge=0, le=2**32 - 1)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    dataset_id: str | None = Field(default=None, min_length=1, max_length=512)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator('parameters', 'metadata')
    @classmethod
    def finite_json(cls, value):
        json.dumps(value, allow_nan=False)
        return value

    @field_validator('code', 'experiment_id')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Must not be blank')
        return value


class ExecutionError(Model):
    type: str
    message: str
    traceback: str | None = None


class Artifact(Model):
    """Reserved metadata contract; artifact generation is a later feature."""
    name: str
    media_type: str
    path: str


class ExecutionOutput(Model):
    status: Literal['success', 'error', 'timeout']
    stdout: str = ''
    stderr: str = ''
    execution_time: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    exit_code: int
    metrics: dict[str, Annotated[float, Field(allow_inf_nan=False)]] = Field(default_factory=dict)
    artifacts: list[Artifact] = Field(default_factory=list)
    error: ExecutionError | None = None
    execution_metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator('execution_metadata')
    @classmethod
    def finite_metadata(cls, value):
        json.dumps(value, allow_nan=False)
        return value

    @model_validator(mode='after')
    def consistent_status(self):
        if self.status == 'success':
            if self.exit_code != 0 or self.error is not None:
                raise ValueError('Successful output requires exit_code 0 and no error')
        elif self.exit_code == 0 or self.error is None:
            raise ValueError('Failed output requires a nonzero exit_code and error details')
        return self


class ExperimentResult(ExecutionOutput):
    experiment_id: str
    parameters: dict[str, JsonValue]
    random_seed: int

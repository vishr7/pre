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
    """Legacy artifact contract retained for executor compatibility."""
    name: str
    media_type: str
    path: str


class FigureArtifact(Model):
    artifact_id: str = Field(pattern=r'^[0-9a-f]{32}-[0-9a-f]{32}$')
    experiment_id: str = Field(min_length=1, max_length=128)
    artifact_type: Literal['figure'] = 'figure'
    filename: str = Field(pattern=r'^[0-9a-f]{32}\.png$')
    mime_type: Literal['image/png'] = 'image/png'
    size_bytes: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    artifact_reference: str = Field(pattern=r'^[0-9a-f]{32}-[0-9a-f]{32}$')

    @model_validator(mode='after')
    def consistent_reference(self):
        if self.artifact_reference != self.artifact_id:
            raise ValueError('Artifact reference must equal its opaque identifier')
        if self.filename != self.artifact_id.split('-')[1] + '.png':
            raise ValueError('Filename must match the artifact identifier')
        return self


class ExecutionOutput(Model):
    status: Literal['success', 'error', 'timeout']
    stdout: str = ''
    stderr: str = ''
    execution_time: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    exit_code: int
    metrics: dict[str, Annotated[float, Field(allow_inf_nan=False)]] = Field(default_factory=dict)
    artifacts: list[FigureArtifact | Artifact] = Field(default_factory=list)
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


class DatasetInspectionRequest(Model):
    dataset_id: str = Field(min_length=1, max_length=128)


DatasetOperation = Literal['drop_missing', 'fill_mean', 'fill_median', 'drop_duplicates',
                           'standardize', 'minmax', 'select_columns', 'drop_columns']


class TransformationOperation(Model):
    operation: DatasetOperation
    columns: list[str] = Field(default_factory=list, max_length=1000)
    ddof: int | None = Field(default=None, ge=0, le=1)

    @model_validator(mode='after')
    def valid_options(self):
        if self.operation != 'drop_duplicates' and not self.columns:
            raise ValueError('Explicit columns are required for this operation')
        if any(not name.strip() for name in self.columns) or len(set(self.columns)) != len(self.columns):
            raise ValueError('Column names must be nonblank and unique')
        if self.operation != 'standardize' and self.ddof is not None:
            raise ValueError('ddof applies only to standardize')
        return self


class DatasetProcessingRequest(DatasetInspectionRequest):
    transformations: list[TransformationOperation] = Field(default_factory=list, max_length=50)


FiniteNumber = Annotated[float, Field(allow_inf_nan=False)]


class DatasetColumnSummary(Model):
    name: str
    dtype: str
    numeric: bool
    categorical: bool
    missing_count: int = Field(ge=0)
    unique_count: int = Field(ge=0)
    statistics: dict[str, FiniteNumber | None] = Field(default_factory=dict)


class DatasetSummary(Model):
    dataset_id: str
    filename: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    size_bytes: int = Field(ge=0)
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    columns: list[DatasetColumnSummary]
    numeric_columns: list[str]
    non_numeric_columns: list[str]
    categorical_columns: list[str]
    duplicate_rows: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)


class TransformationLogEntry(Model):
    operation: DatasetOperation
    columns: list[str]
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    rows_before: int
    rows_after: int
    columns_before: list[str]
    columns_after: list[str]
    dtypes_before: dict[str, str] = Field(default_factory=dict)
    dtypes_after: dict[str, str] = Field(default_factory=dict)
    rows_removed: int
    affected_values: int | None = None
    computed_values: dict[str, dict[str, int | FiniteNumber]] = Field(default_factory=dict)
    status: Literal['success', 'error']
    warnings: list[str] = Field(default_factory=list)
    error: ExecutionError | None = None


class ProcessedDatasetReference(Model):
    """Locator/provenance only, not a host path or a proof of authorization."""
    dataset_id: str
    artifact_reference: str = Field(pattern=r'^[0-9a-f]{32}-[0-9a-f]{32}$')
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    transformation_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class DatasetArtifact(ProcessedDatasetReference):
    artifact_id: str = Field(pattern=r'^[0-9a-f]{32}-[0-9a-f]{32}$')
    processing_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    artifact_type: Literal['dataset'] = 'dataset'
    filename: str = Field(pattern=r'^[0-9a-f]{32}\.csv$')
    mime_type: Literal['text/csv'] = 'text/csv'
    size_bytes: int = Field(gt=0)

    @model_validator(mode='after')
    def consistent_reference(self):
        run, token = self.artifact_id.split('-')
        if (self.artifact_reference != self.artifact_id or self.processing_id != run
                or self.filename != token + '.csv'):
            raise ValueError('Dataset artifact identifiers must agree')
        return self

    def to_reference(self) -> ProcessedDatasetReference:
        return ProcessedDatasetReference(**self.model_dump(include=set(ProcessedDatasetReference.model_fields)))


class DatasetProvenance(Model):
    dataset_id: str
    original_filename: str
    source_sha256: str
    processed_sha256: str | None
    original_rows: int
    original_columns: int
    final_rows: int
    final_columns: int
    processing_timestamp: str
    dependencies: dict[str, str]
    transformation_sha256: str


class DatasetProcessingResult(Model):
    dataset_id: str
    status: Literal['success', 'error']
    original_summary: DatasetSummary
    final_summary: DatasetSummary | None
    transformations: list[TransformationLogEntry]
    provenance: DatasetProvenance
    artifact: DatasetArtifact | None = None
    error: ExecutionError | None = None

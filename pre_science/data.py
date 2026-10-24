"""Authorized CSV inspection, explicit transformations and durable local handoff.

No code evaluation, service clients, upload handlers, or automatic cleaning.
"""

from collections.abc import Mapping
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
from uuid import uuid4

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype
from pydantic import Field

from .schemas import (
    DatasetArtifact, DatasetColumnSummary, DatasetInspectionRequest,
    DatasetProcessingRequest, DatasetProcessingResult, DatasetProvenance,
    DatasetSummary, ExecutionError, Model, TransformationLogEntry,
)


class DatasetError(ValueError):
    """Safe validation/IO error; never includes raw input bytes or host paths."""


class DatasetLimits(Model):
    max_file_bytes: int = Field(default=10_000_000, ge=1, le=50_000_000)
    max_output_bytes: int = Field(default=20_000_000, ge=1, le=50_000_000)
    max_rows: int = Field(default=100_000, ge=1, le=1_000_000)
    max_columns: int = Field(default=200, ge=1, le=1000)
    max_cells: int = Field(default=2_000_000, ge=1, le=5_000_000)
    max_memory_bytes: int = Field(default=100_000_000, ge=1, le=500_000_000)


def _linked(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def _root(directory, *, create=False):
    path = Path(directory).absolute()
    if any(_linked(part) for part in (path, *path.parents)):
        raise DatasetError('Controlled directories cannot contain filesystem links')
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise DatasetError('Controlled dataset directory is unavailable')
    return path.resolve()


def _path(root, reference):
    if (not isinstance(reference, str) or not reference or '\\' in reference
            or ':' in reference or '\0' in reference or reference.startswith('/')
            or any(part in ('', '.', '..') for part in reference.split('/'))):
        raise DatasetError('Invalid relative CSV reference')
    relative = PurePosixPath(reference)
    if relative.suffix.lower() != '.csv':
        raise DatasetError('Only CSV files are supported')
    path = root.joinpath(*relative.parts)
    if any(_linked(part) for part in (root, *root.parents)):
        raise DatasetError('Controlled directories cannot contain filesystem links')
    current = root
    for part in relative.parts:
        current = current / part
        if _linked(current):
            raise DatasetError('CSV references cannot contain filesystem links')
    if not path.resolve().is_relative_to(root):
        raise DatasetError('CSV reference must remain in the controlled directory')
    return path


def _read(path, limit):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise DatasetError('CSV must be a regular file without filesystem links')
        flags = (os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                 | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(os.open(path, flags), 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise DatasetError('CSV must be a regular file without filesystem links')
            if opened.st_size > limit:
                raise DatasetError('CSV exceeds the configured file-size limit')
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise DatasetError('CSV exceeds the configured file-size limit')
        return data
    except OSError:
        raise DatasetError('CSV file is missing or unavailable') from None


def _numeric(series):
    return is_numeric_dtype(series.dtype) and not is_bool_dtype(series.dtype)


class _CSVOutput(io.StringIO):
    def __init__(self, limit):
        super().__init__()
        self.limit, self.size = limit, 0

    def write(self, text):
        size = len(text.encode('utf-8'))
        if self.size + size > self.limit:
            raise DatasetError('Processed CSV exceeds the configured output size limit')
        self.size += size
        return super().write(text)


def _check_frame(frame, limits):
    rows, columns = frame.shape
    if columns == 0:
        raise DatasetError('A dataset must retain at least one column')
    if rows > limits.max_rows or columns > limits.max_columns or rows * columns > limits.max_cells:
        raise DatasetError('CSV exceeds configured row, column, or cell limits')
    if int(frame.memory_usage(index=True, deep=True).sum()) > limits.max_memory_bytes:
        raise DatasetError('Dataset exceeds the configured memory limit')
    for name in frame:
        series = frame[name]
        if _numeric(series) and not np.isfinite(series.dropna().to_numpy(dtype=float)).all():
            raise DatasetError('Non-finite numerical values are unsupported; clean the source explicitly')


def _parse(data, limits):
    try:
        text = data.decode('utf-8-sig')
        if '\0' in text:
            raise DatasetError('CSV cannot contain NUL characters')
        records = csv.reader(io.StringIO(text, newline=''), strict=True)
        header = next(records, None)
        if not header or any(not name.strip() for name in header) or len(set(header)) != len(header):
            raise DatasetError('CSV needs a nonblank, unique column header')
        if len(header) > limits.max_columns:
            raise DatasetError('CSV exceeds the configured column limit')
        count = 0
        for row in records:
            if not row:  # Empty physical records, not records of empty fields.
                continue
            if len(row) != len(header):
                raise DatasetError('CSV rows must have the same field count as the header')
            if any(value.strip().lower() in ('inf', '+inf', '-inf', 'infinity', '+infinity', '-infinity')
                   for value in row):
                raise DatasetError('Non-finite numerical values are unsupported')
            count += 1
            if count > limits.max_rows or count * len(header) > limits.max_cells:
                raise DatasetError('CSV exceeds configured row or cell limits')
        frame = pd.read_csv(io.StringIO(text), keep_default_na=False,
                            na_values=['', 'NA', 'NaN', 'nan', 'NULL', 'null'],
                            skip_blank_lines=False)
        # Match CSV record semantics: blank records are ignored by the strict reader.
        if count != len(frame):
            raise DatasetError('Blank records are unsupported; remove blank lines explicitly')
    except (UnicodeError, csv.Error, pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
        if isinstance(exc, DatasetError):
            raise
        raise DatasetError('Invalid UTF-8 comma-delimited CSV structure') from None
    _check_frame(frame, limits)
    return frame


def _summary(frame, dataset_id, filename, data):
    columns, warnings = [], []
    if frame.empty:
        warnings.append('Dataset has zero rows; numerical statistics are unavailable')
    for name in frame:
        series = frame[name]
        numeric = _numeric(series)
        statistics = {}
        if numeric:
            finite = series.dropna().astype(float)
            with np.errstate(all='ignore'):
                values = {'count': len(finite), 'mean': finite.mean(),
                          'std': finite.std(ddof=0), 'min': finite.min(),
                          'q25': finite.quantile(.25), 'median': finite.median(),
                          'q75': finite.quantile(.75), 'max': finite.max()}
            for key, value in values.items():
                statistics[key] = float(value) if math.isfinite(float(value)) else None
            if len(finite) == 0:
                warnings.append(f'Column {name}: no observed numeric values')
            elif any(value is None for value in statistics.values()):
                warnings.append(f'Column {name}: some statistics overflowed and are unavailable')
        columns.append(DatasetColumnSummary(
            name=name, dtype=str(series.dtype), numeric=numeric, categorical=not numeric,
            missing_count=int(series.isna().sum()), unique_count=int(series.nunique(dropna=True)),
            statistics=statistics,
        ))
    return DatasetSummary(
        dataset_id=dataset_id, filename=filename, sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data), row_count=len(frame), column_count=len(frame.columns), columns=columns,
        numeric_columns=[c.name for c in columns if c.numeric],
        non_numeric_columns=[c.name for c in columns if not c.numeric],
        categorical_columns=[c.name for c in columns if c.categorical],
        duplicate_rows=int(frame.duplicated().sum()), warnings=warnings,
    )


class DatasetArtifactStore:
    """CSV handoff with opaque IDs; the caller owns access control and retention."""

    def __init__(self, root='.runtime/dataset-artifacts', *, max_bytes=20_000_000):
        self.root = _root(root, create=True)
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 1 <= max_bytes <= 50_000_000:
            raise DatasetError('Invalid artifact size limit')
        self.max_bytes = max_bytes

    def _artifact_path(self, artifact_id):
        if not isinstance(artifact_id, str) or not re.fullmatch(r'[0-9a-f]{32}-[0-9a-f]{32}', artifact_id):
            raise DatasetError('Invalid dataset artifact identifier')
        run, token = artifact_id.split('-')
        return _path(self.root, f'{run}/{token}.csv')

    def save(self, data, *, dataset_id, source_sha256, transformation_sha256):
        if len(data) > self.max_bytes:
            raise DatasetError('Processed CSV exceeds the artifact size limit')
        run, token = uuid4().hex, uuid4().hex
        artifact_id = f'{run}-{token}'
        artifact = DatasetArtifact(
            dataset_id=dataset_id, artifact_reference=artifact_id, artifact_id=artifact_id,
            processing_id=run, filename=token + '.csv', size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(), source_sha256=source_sha256,
            transformation_sha256=transformation_sha256,
        )
        target = self._artifact_path(artifact_id)
        try:
            target.parent.mkdir()
            try:
                with target.open('xb') as stream:
                    stream.write(data)
            except BaseException:
                target.unlink(missing_ok=True)
                target.parent.rmdir()
                raise
        except OSError:
            raise DatasetError('Unable to persist processed CSV artifact') from None
        return artifact

    def retrieve(self, artifact_id):
        return _read(self._artifact_path(artifact_id), self.max_bytes)

    def cleanup(self, artifact_id):
        target = self._artifact_path(artifact_id)
        try:
            target.unlink(missing_ok=True)
            try:
                target.parent.rmdir()
            except OSError:
                pass  # Never recursively remove unrelated files.
        except OSError:
            raise DatasetError('Unable to clean up dataset artifact') from None


class DatasetService:
    def __init__(self, dataset_root, authorized_datasets: Mapping[str, str], *,
                 artifact_store: DatasetArtifactStore | None = None, limits: DatasetLimits | None = None):
        self.root = _root(dataset_root)
        self.authorized = dict(authorized_datasets)
        self.limits = limits if limits is not None else DatasetLimits()
        self.store = artifact_store if artifact_store is not None else DatasetArtifactStore(
            max_bytes=self.limits.max_output_bytes)

    def _load(self, request):
        if request.dataset_id not in self.authorized:
            raise DatasetError('Dataset identifier is not authorized')
        reference = self.authorized[request.dataset_id]
        path = _path(self.root, reference)
        data = _read(path, self.limits.max_file_bytes)
        frame = _parse(data, self.limits)
        return frame, data, path.name

    def inspect(self, specification: DatasetInspectionRequest | dict) -> DatasetSummary:
        request = DatasetInspectionRequest.model_validate(
            specification.model_dump() if isinstance(specification, DatasetInspectionRequest) else specification)
        frame, data, filename = self._load(request)
        return _summary(frame, request.dataset_id, filename, data)

    def process(self, specification: DatasetProcessingRequest | dict) -> DatasetProcessingResult:
        request = DatasetProcessingRequest.model_validate(
            specification.model_dump() if isinstance(specification, DatasetProcessingRequest) else specification)
        frame, source, filename = self._load(request)
        original = _summary(frame, request.dataset_id, filename, source)
        logs, error, artifact, final = [], None, None, None
        timestamp = datetime.now(timezone.utc).isoformat()
        for operation in request.transformations:
            log = TransformationLogEntry(
                operation=operation.operation, columns=operation.columns or list(frame.columns),
                parameters={'ddof': operation.ddof or 0} if operation.operation == 'standardize' else {},
                rows_before=len(frame), rows_after=len(frame), columns_before=list(frame.columns),
                columns_after=list(frame.columns), rows_removed=0, status='success',
                dtypes_before={name: str(dtype) for name, dtype in frame.dtypes.items()},
                dtypes_after={name: str(dtype) for name, dtype in frame.dtypes.items()},
            )
            try:
                candidate = self._transform(frame, operation, log)
                _check_frame(candidate, self.limits)
                frame = candidate
                log.rows_after = len(frame)
                log.columns_after = list(frame.columns)
                log.dtypes_after = {name: str(dtype) for name, dtype in frame.dtypes.items()}
                log.rows_removed = log.rows_before - log.rows_after
                if frame.empty:
                    log.warnings.append('Transformation left zero rows')
            except DatasetError as exc:
                error = ExecutionError(type='DatasetError', message=str(exc))
                log.status, log.error = 'error', error
                log.affected_values, log.computed_values = None, {}
            logs.append(log)
            if error:
                break
        history_hash = hashlib.sha256(json.dumps(
            [log.model_dump(mode='json') for log in logs], sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        if not error:
            try:
                # Deterministic serialization; no index, LF records, UTF-8 bytes.
                if request.transformations:
                    with _CSVOutput(self.limits.max_output_bytes) as buffer:
                        frame.to_csv(buffer, index=False, lineterminator='\n')
                        output = buffer.getvalue().encode('utf-8')
                else:
                    output = source  # Inspection/no-op processing must not rewrite source values.
                if len(output) > self.limits.max_output_bytes:
                    raise DatasetError('Processed CSV exceeds the configured output size limit')
                artifact = self.store.save(output, dataset_id=request.dataset_id,
                                           source_sha256=original.sha256, transformation_sha256=history_hash)
                final = _summary(frame, request.dataset_id, artifact.filename, output)
            except DatasetError as exc:
                error = ExecutionError(type='DatasetError', message=str(exc))
        return DatasetProcessingResult(
            dataset_id=request.dataset_id, status='error' if error else 'success',
            original_summary=original, final_summary=final, transformations=logs,
            artifact=artifact, error=error,
            provenance=DatasetProvenance(
                dataset_id=request.dataset_id, original_filename=filename, source_sha256=original.sha256,
                processed_sha256=artifact.sha256 if artifact else None,
                original_rows=original.row_count, original_columns=original.column_count,
                final_rows=len(frame), final_columns=len(frame.columns), processing_timestamp=timestamp,
                dependencies={'pandas': pd.__version__, 'numpy': np.__version__},
                transformation_sha256=history_hash,
            ),
        )

    def _transform(self, frame, operation, log):
        columns = log.columns
        if any(name not in frame.columns for name in columns):
            raise DatasetError('Requested columns do not exist in the current dataset')
        result = frame.copy(deep=True)
        kind = operation.operation
        if kind == 'drop_missing':
            result = result.dropna(subset=columns)
        elif kind == 'drop_duplicates':
            result = result.drop_duplicates(subset=columns, keep='first')
            log.parameters = {'keep': 'first'}
        elif kind == 'select_columns':
            result = result.loc[:, columns]
        elif kind == 'drop_columns':
            result = result.drop(columns=columns)
        else:
            if any(not _numeric(result[name]) for name in columns):
                raise DatasetError('Numerical transformations require numeric, non-boolean columns')
            log.affected_values = 0
            for name in columns:
                series = result[name].astype(float)
                if series.count() == 0:
                    raise DatasetError('Numerical transformation has no observed values')
                with np.errstate(all='ignore'):
                    if kind in ('fill_mean', 'fill_median'):
                        value = float(series.mean() if kind == 'fill_mean' else series.median())
                        computed = {'fill_value': value, 'filled_count': int(series.isna().sum())}
                        transformed = series.fillna(value)
                    elif kind == 'standardize':
                        ddof = operation.ddof or 0
                        mean, scale = float(series.mean()), float(series.std(ddof=ddof))
                        computed = {'mean': mean, 'std': scale, 'ddof': ddof}
                        if not math.isfinite(scale) or scale <= 0:
                            raise DatasetError('Standardization requires a positive, finite standard deviation')
                        transformed = (series - mean) / scale
                    else:  # validated operation is minmax
                        low, high = float(series.min()), float(series.max())
                        span = high - low
                        computed = {'min': low, 'max': high, 'range': span}
                        if not math.isfinite(span) or span <= 0:
                            raise DatasetError('Min-max scaling requires a positive, finite range')
                        transformed = (series - low) / span
                if not all(math.isfinite(value) for value in computed.values()):
                    raise DatasetError('Computed transformation values overflowed')
                changed = ~(series.eq(transformed) | (series.isna() & transformed.isna()))
                log.affected_values += int(changed.sum())
                log.computed_values[name] = computed
                if kind in ('standardize', 'minmax') and series.isna().any():
                    log.warnings.append(f'Column {name}: missing values retained; statistics exclude them')
                result[name] = transformed
        return result.reset_index(drop=True)

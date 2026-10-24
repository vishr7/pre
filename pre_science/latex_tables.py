"""Deterministic presentation of recorded evidence; no execution or LaTeX compilation."""

from collections.abc import Mapping
from datetime import datetime, timezone
import math
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .schemas import ExperimentResult, Model, ReplicationReport

TableType = Literal['experiment', 'comparison', 'replication']


class LatexTableRequest(Model):
    table_type: TableType
    source_ids: list[str] = Field(min_length=1, max_length=100)
    selected_metrics: list[str] = Field(default_factory=list, max_length=100)
    caption: str = Field(default='Recorded scientific results', max_length=2000)
    label: str = Field(default='tab:scientific-results', max_length=128)
    decimal_precision: int = Field(default=4, ge=0, le=12)
    number_format: Literal['fixed', 'scientific'] = 'fixed'
    placement: Literal['htbp', 'h', 't', 'b', 'p', '!htbp'] | None = 'htbp'
    metric_names: dict[str, str] = Field(default_factory=dict)
    experiment_names: dict[str, str] = Field(default_factory=dict)
    missing_value: str = Field(default='--', min_length=1, max_length=64)

    @field_validator('label')
    @classmethod
    def valid_label(cls, value):
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9:._-]*', value):
            raise ValueError('Label must start with a letter and contain only letters, digits, colon, dot, underscore or hyphen')
        return value

    @model_validator(mode='after')
    def valid_selection(self):
        for values in (self.source_ids, self.selected_metrics):
            if any(not value.strip() for value in values) or len(values) != len(set(values)):
                raise ValueError('Identifiers and selected metrics must be nonblank and unique')
        if self.table_type != 'comparison' and len(self.source_ids) != 1:
            raise ValueError('This table type requires exactly one source')
        return self


class LatexTableResponse(Model):
    latex_source: str
    table_type: TableType
    source_ids: list[str]
    included_metrics: list[str]
    missing_metrics: list[str]
    missing_by_source: dict[str, list[str]]
    warnings: list[str]
    generation_timestamp: str
    compiled: Literal[False] = False


def escape_latex(value: str) -> str:
    """Escape each original character once, including command and comment syntax."""
    replacements = {'\\': r'\textbackslash{}', '_': r'\_', '%': r'\%', '$': r'\$',
                    '&': r'\&', '#': r'\#', '{': r'\{', '}': r'\}',
                    '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
    return ''.join(replacements.get(char, char if char.isprintable() else ' ') for char in value)


def generate_latex_table(request: LatexTableRequest | dict,
                         scientific_records: Mapping[str, ExperimentResult | ReplicationReport]) -> LatexTableResponse:
    """Resolve IDs from backend-authorized records; never execute supplied code.

    Empty selected_metrics means recorded metrics in their existing order (union
    for comparisons). Runtime is included only if explicitly reported as a metric.
    Records are revalidated to reject mutated/non-finite model instances.
    """
    request = LatexTableRequest.model_validate(request.model_dump() if isinstance(request, LatexTableRequest) else request)
    records = []
    expected = ReplicationReport if request.table_type == 'replication' else ExperimentResult
    for source_id in request.source_ids:
        if source_id not in scientific_records:
            raise ValueError('A requested scientific record is unavailable')
        record = scientific_records[source_id]
        if not isinstance(record, expected):
            raise ValueError('Scientific record type does not match the requested table type')
        records.append(expected.model_validate(record.model_dump(warnings=False)))
    available = list(dict.fromkeys(name for record in records for name in
        ([item.name for item in record.comparisons] if isinstance(record, ReplicationReport) else record.metrics)))
    metrics = request.selected_metrics or available
    warnings, missing = [], {source_id: [] for source_id in request.source_ids}
    if not metrics:
        warnings.append('No recorded metrics are available; no numerical results were invented.')
    marker = escape_latex(request.missing_value)

    def number(value):
        if value is None:
            return marker
        if isinstance(value, bool) or not math.isfinite(value):
            raise ValueError('Table values must be finite recorded numbers')
        if request.number_format == 'scientific':
            mantissa, exponent = format(value, f'.{request.decimal_precision}e').split('e')
            return r'\(' + mantissa + r' \times 10^{' + str(int(exponent)) + r'}\)'
        return format(value, f'.{request.decimal_precision}f')

    def metric_name(name):
        return escape_latex(request.metric_names.get(name, name))

    rows = []
    if request.table_type == 'replication':
        report = records[0]
        headers = ['Metric', 'Reference', 'Reproduced', 'Absolute Difference', 'Agreement Status']
        comparisons = {item.name: item for item in report.comparisons}
        for name in metrics:
            item = comparisons.get(name)
            if item is None or item.published_value is None or item.reproduced_value is None:
                missing[request.source_ids[0]].append(name)
            rows.append([metric_name(name), number(item.published_value if item else None),
                         number(item.reproduced_value if item else None),
                         number(item.absolute_difference if item else None),
                         escape_latex(item.status) if item else 'unavailable'])
        warnings.extend(['Numerical agreement does not establish scientific fidelity.',
                         f'Reference source: {report.paper.source_kind}.',
                         f'Replication status: {report.status}; execution: {report.execution_status}.'])
        warnings.extend(report.warnings)
        note = f'Reference source: {report.paper.source_kind}. Status: {report.status}. Numerical agreement does not establish scientific fidelity.'
    else:
        headers = ['Metric', 'Value'] if request.table_type == 'experiment' else ['Experiment', 'Execution status'] + [metric_name(name) for name in metrics]
        for source_id, record in zip(request.source_ids, records):
            values = []
            for name in metrics:
                value = record.metrics.get(name)
                if value is None:
                    missing[source_id].append(name)
                values.append(number(value))
            if record.status != 'success':
                warnings.append(f'Source {source_id}: execution {record.status}; recorded metrics may be partial.')
            if request.table_type == 'experiment':
                rows.extend([[metric_name(name), value] for name, value in zip(metrics, values)])
            else:
                rows.append([escape_latex(request.experiment_names.get(source_id, record.experiment_id)), record.status] + values)
        note = (f'Execution status: {records[0].status}. Metrics from failed executions may be partial.'
                if request.table_type == 'experiment' else 'Recorded executions; failed or timed-out rows may contain partial metrics.')
    for source_id, names in missing.items():
        if names:
            warnings.append(f'Source {source_id} has unavailable selected metrics: ' + ', '.join(names))
    placement = f'[{request.placement}]' if request.placement else ''
    lines = [r'\begin{table}' + placement, r'\centering',
             r'\caption{' + escape_latex(request.caption) + ' ' + escape_latex(note) + '}',
             r'\label{' + request.label + '}', r'\begin{tabular}{' + 'l' * len(headers) + '}', r'\hline',
             ' & '.join(headers) + r' \\', r'\hline']
    lines += [' & '.join(row) + r' \\' for row in rows]
    lines += [r'\hline', r'\end{tabular}', r'\end{table}']
    return LatexTableResponse(
        latex_source='\n'.join(lines) + '\n', table_type=request.table_type,
        source_ids=request.source_ids, included_metrics=metrics,
        missing_metrics=list(dict.fromkeys(name for names in missing.values() for name in names)),
        missing_by_source=missing, warnings=warnings,
        generation_timestamp=datetime.now(timezone.utc).isoformat(),
    )

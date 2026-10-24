"""Presentation tests use structured fixtures; the demo test executes real code."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from pydantic import ValidationError

from pre_science.demo_latex_tables import run_demo
from pre_science.demo_replicate import baseline_specification
from pre_science.experiment import ExperimentService
from pre_science.latex_tables import LatexTableRequest, LatexTableResponse, escape_latex, generate_latex_table
from pre_science.replicate import ReplicationService, specification_digest
from pre_science.schemas import ExecutionError, ExecutionOutput, ExperimentResult, ResearcherApproval
from unittest.mock import Mock


def result(**updates):
    data = dict(status='success', exit_code=0, experiment_id='baseline', parameters={}, random_seed=42,
                metrics={'accuracy': .9123456789, 'zero': 0., 'negative': -1.23456789})
    data.update(updates)
    return ExperimentResult(**data)


def generate(record=None, **options):
    return generate_latex_table(dict(table_type='experiment', source_ids=['a'], **options),
                                {'a': result() if record is None else record})


def test_single_schema_precision_and_original_values():
    record = result()
    before = record.model_dump_json()
    table = generate(record, decimal_precision=3)
    assert '0.912' in table.latex_source and '-1.235' in table.latex_source and '0.000' in table.latex_source
    assert table.included_metrics == ['accuracy', 'zero', 'negative']
    assert record.model_dump_json() == before
    assert table.compiled is False
    assert LatexTableResponse.model_validate_json(table.model_dump_json()) == table


def test_comparison_selected_columns_and_missing():
    table = generate_latex_table({'table_type': 'comparison', 'source_ids': ['a', 'b'],
        'selected_metrics': ['accuracy', 'missing'], 'experiment_names': {'b': 'Variant_A'}},
        {'a': result(), 'b': result(metrics={'accuracy': .95})})
    assert 'Variant\\_A' in table.latex_source
    assert table.missing_by_source == {'a': ['missing'], 'b': ['missing']}
    assert table.missing_metrics == ['missing']
    assert 'negative' not in table.latex_source


def test_failed_execution_retains_partial_metrics_and_marks_status():
    table = generate(result(status='error', exit_code=1, error=ExecutionError(type='ValueError', message='failure')))
    assert 'Execution status: error' in table.latex_source
    assert '0.9123' in table.latex_source and table.warnings


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_rejected_even_for_mutated_records(value):
    record = result()
    record.metrics['bad'] = value
    with pytest.raises(ValidationError):
        generate(record)


def test_all_text_escaped_once_and_not_interpreted():
    text = r'\input{secret}_%$&#~^'
    escaped = escape_latex(text)
    assert escaped == r'\textbackslash{}input\{secret\}\_\%\$\&\#\textasciitilde{}\textasciicircum{}'
    table = generate(caption=text, metric_names={'accuracy': text}, missing_value=text,
                     selected_metrics=['accuracy', 'absent'])
    assert escaped in table.latex_source
    assert r'\input{' not in table.latex_source


@pytest.mark.parametrize('options', [{'label': r'tab:x}\input{secret}'}, {'label': 'tab:x\n'},
    {'placement': r'h]\input{secret}'}, {'decimal_precision': 13}, {'decimal_precision': -1},
    {'selected_metrics': ['accuracy', 'accuracy']}, {'source_ids': []}])
def test_invalid_options(options):
    with pytest.raises(ValidationError):
        LatexTableRequest.model_validate({'table_type': 'experiment', 'source_ids': ['a'], **options})


def test_empty_records_and_empty_metrics():
    with pytest.raises(ValueError, match='unavailable'):
        generate_latex_table({'table_type': 'experiment', 'source_ids': ['a']}, {})
    table = generate(result(metrics={}))
    assert not table.included_metrics and table.warnings
    table = generate(result(metrics={}), selected_metrics=['unknown'], missing_value='N/A')
    assert 'N/A' in table.latex_source and table.missing_metrics == ['unknown']


def test_deterministic_source_with_safe_label_and_optional_placement():
    first = generate(label='tab:results_1', placement=None)
    second = generate(label='tab:results_1', placement=None)
    assert first.latex_source == second.latex_source
    assert first.latex_source.startswith('\\begin{table}\n')
    assert json.loads(first.model_dump_json())['compiled'] is False


def test_scientific_notation_and_display_names():
    table = generate(result(metrics={'small': -1.234e-9}), number_format='scientific',
                     decimal_precision=2, metric_names={'small': 'Small value'})
    assert r'Small value & \(-1.23 \times 10^{-9}\)' in table.latex_source


def test_replication_uses_existing_conclusion_without_recomputation():
    spec = baseline_specification()
    spec.approval = ResearcherApproval(approved=True, approved_by='fixture', specification_sha256=specification_digest(spec))
    executor = Mock()
    executor.execute.return_value = ExecutionOutput(status='success', exit_code=0, metrics={'mean': 30., 'std': 14.142135623730951})
    report = ReplicationService(ExperimentService(executor)).run(spec)
    # Presentation must copy the supplied comparison, even when rounded values look equal.
    report.comparisons[0].status = 'different'
    report.comparisons[0].absolute_difference = 0.00001
    table = generate_latex_table({'table_type': 'replication', 'source_ids': ['r'],
        'selected_metrics': ['mean', 'unknown'], 'decimal_precision': 2}, {'r': report})
    assert '30.00 & 30.00 & 0.00 & different' in table.latex_source
    assert 'local\\_baseline' in table.latex_source
    assert table.missing_metrics == ['unknown']
    assert 'does not establish scientific fidelity' in table.latex_source
    with pytest.raises(ValueError, match='type'):
        generate_latex_table({'table_type': 'experiment', 'source_ids': ['r']}, {'r': report})


def test_real_services_demo(tmp_path):
    payload = run_demo(tmp_path)
    assert payload['presentation_values_verified']
    assert payload['records']['baseline']['metrics']['mean'] == 30.
    assert payload['records']['variant']['metrics']['mean'] == 32.
    assert payload['records']['replication']['all_published_metrics_agree'] is True
    assert len(list(tmp_path.glob('*.tex'))) == 3


def test_optional_tectonic_compile(tmp_path):
    executable = shutil.which(os.environ.get('PRE_TECTONIC', 'tectonic'))
    if executable is None:
        executable = next((str(candidate.resolve()) for candidate in
                           (Path('.runtime/bin/tectonic'), Path('.runtime/bin/tectonic.exe'))
                           if candidate.is_file()), None)
    if executable is None:
        pytest.skip('Tectonic is unavailable')
    table = generate(caption=r'Escaping _ % $ & # { } ~ ^ \\', metric_names={'accuracy': r'Accuracy_%'})
    document = tmp_path / 'table.tex'
    document.write_text('\\documentclass{article}\n\\begin{document}\n' + table.latex_source + '\\end{document}\n', encoding='utf-8')
    process = subprocess.run([executable, '--untrusted', '--only-cached', '--outdir', str(tmp_path), str(document)],
                             capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stdout + process.stderr
    assert (tmp_path / 'table.pdf').is_file()

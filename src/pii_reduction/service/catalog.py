"""Reading the configuration directory: which datasets exist, and what each one is.

Everything here is a *configuration* answer. Nothing in this module opens a source,
and that is not an oversight to be corrected later — a "show me a few rows so I can
pick columns" endpoint is forbidden by name in ADR-0026, and it is the one this
module would grow if it ever learned how to read.
"""

from __future__ import annotations

from pathlib import Path

from pii_reduction.config.errors import ConfigurationError
from pii_reduction.config.fingerprint import config_fingerprint
from pii_reduction.config.loader import load_resolved_dataset, load_yaml_mapping
from pii_reduction.config.registries import (
    DATABRICKS_DESTINATION_TYPES,
    DATABRICKS_SOURCE_TYPES,
)
from pii_reduction.config.resolved import ResolvedDataset
from pii_reduction.service.errors import UnknownDatasetError
from pii_reduction.service.knobs import OFFERABLE_OPTION_NAMES
from pii_reduction.service.models import ColumnSummary, DatasetSummary

__all__ = [
    "check_dataset_names",
    "declared_dataset_names",
    "describe_dataset",
    "list_dataset_names",
    "load_dataset",
    "requires_databricks",
]

DATASETS_DIR = "datasets"


def list_dataset_names(configs_dir: Path) -> tuple[str, ...]:
    """Every dataset the service could run, by name. Sorted, so the answer is stable."""
    directory = configs_dir / DATASETS_DIR
    if not directory.is_dir():
        return ()
    return tuple(sorted(path.stem for path in directory.glob("*.yaml")))


def declared_dataset_names(configs_dir: Path) -> dict[str, str]:
    """File stem → the ``dataset.name`` inside it, for every dataset file.

    Read with a bare YAML load rather than the resolver: this answers a *naming*
    question, it runs on every save, and resolving builds the whole layered
    configuration. A file that cannot be read or does not declare a name is reported
    under its own stem — the resolver will produce the real error when somebody
    actually runs it.
    """
    declared: dict[str, str] = {}
    for path in sorted((configs_dir / DATASETS_DIR).glob("*.yaml")):
        try:
            raw = load_yaml_mapping(path)
        except ConfigurationError:
            declared[path.stem] = path.stem
            continue
        section = raw.get("dataset")
        name = section.get("name") if isinstance(section, dict) else None
        declared[path.stem] = str(name) if isinstance(name, str) and name else path.stem
    return declared


def taken_dataset_names(configs_dir: Path) -> frozenset[str]:
    """Every name already spoken for — file stems **and** declared names.

    A new dataset may take neither. The stem is where its file lands; the declared
    name is where its *output* lands (``<name>.csv``, ``<name>_reduced``), and two
    datasets sharing either one collide.
    """
    declared = declared_dataset_names(configs_dir)
    return frozenset(declared) | frozenset(declared.values())


def check_dataset_names(configs_dir: Path) -> None:
    """Refuse at startup a configuration directory whose names already collide.

    Two files declaring the same name write over each other's output, and a file
    declaring another file's stem makes that other file unreachable. Both are
    operator errors in files the service did not write, so they belong at startup —
    the service refuses to run rather than surfacing them as a 404 blaming an
    innocent dataset.
    """
    declared = declared_dataset_names(configs_dir)
    by_name: dict[str, list[str]] = {}
    for stem, name in sorted(declared.items()):
        by_name.setdefault(name, []).append(stem)
    for name, stems in sorted(by_name.items()):
        if len(stems) > 1:
            raise ConfigurationError(
                f"datasets {', '.join(repr(s) for s in stems)} all declare the name "
                f"{name!r}: they would write over each other's output. Give each a "
                "distinct dataset.name"
            )
        if name != stems[0] and name in declared:
            raise ConfigurationError(
                f"dataset {stems[0]!r} declares the name {name!r}, which is also "
                "another dataset's file name: running it would write over that "
                "dataset's output. Give one of them a different name"
            )


def load_dataset(configs_dir: Path, name: str) -> ResolvedDataset:
    """Resolve one dataset, or say which ones exist.

    The name is checked against the directory listing before the loader sees it, so an
    unknown dataset is a 404 with a menu rather than a file-not-found naming a path
    that came from a request.
    """
    if name not in list_dataset_names(configs_dir):
        available = ", ".join(list_dataset_names(configs_dir)) or "(none)"
        raise UnknownDatasetError(f"unknown dataset {name!r}; available: {available}")
    config = load_resolved_dataset(configs_dir, name)
    # The configuration layer does not require a file's `dataset.name` to match its
    # filename, and several committed configs legitimately differ
    # (`benchmark_plain.yaml` declares `benchmark_corpus_plain`). What is refused is
    # the narrow case that matters: a file whose declared name is *another dataset's
    # file name*. The declared name decides where output lands (`<dataset>.csv`,
    # `<dataset>_reduced`), so running this one would write over that one's
    # artifacts — and a caller who may run one dataset would be reaching another.
    # Configs the service writes always agree, because the builder sets both from the
    # same validated name.
    declared = config.dataset.name
    if declared != name and declared in list_dataset_names(configs_dir):
        raise UnknownDatasetError(
            f"dataset file {name!r} declares the name {declared!r}, which is also a "
            "dataset in this directory: running it would write over that dataset's "
            "output. Give one of them a different name"
        )
    return config


def requires_databricks(source_type: str, destination_type: str) -> bool:
    """True when running this pair needs a Spark session.

    Takes the two type strings rather than a config so the templates — which are not
    resolved datasets — answer the same question through the same rule. One place, so
    a newly-registered Databricks-backed type cannot be right in one and wrong in the
    other.
    """
    return (
        source_type in DATABRICKS_SOURCE_TYPES or destination_type in DATABRICKS_DESTINATION_TYPES
    )


def describe_dataset(config: ResolvedDataset) -> DatasetSummary:
    """The metadata view of a configured dataset.

    Every field is a configuration value: names, types, entity labels, the
    projection, and per column the failure mode and preservation flag. Those three
    are here deliberately — they are what an operator most needs to see before
    triggering a run, because `preserve_original_and_record_error` and
    `projection: full` each change what ends up readable in the output (ADR-0023,
    ADR-0024).
    """
    return DatasetSummary(
        name=config.dataset.name,
        row_id=config.dataset.row_id,
        source_type=config.source.type,
        destination_type=config.destination.type,
        projection=config.destination.projection,
        config_hash=config_fingerprint(config),
        requires_databricks=requires_databricks(config.source.type, config.destination.type),
        columns=tuple(
            ColumnSummary(
                column=policy.column,
                output_column=policy.output_column,
                parser=policy.parser,
                provider_chain=policy.provider_chain,
                reducer=policy.reducer,
                entities=tuple(sorted(policy.entities)),
                language_mode=str(policy.language.mode.value),
                failure_mode=str(policy.failure_mode.value),
                preserve_original=policy.preserve_original,
                # **Only the options the API governs, and only boolean values.**
                #
                # A dataset YAML is hand-writable and `DatasetConfig.parser_options`
                # is `dict[str, Any]`, so a template-side option can hold a delimiter
                # list, a length, or a key that is not a parser option at all. This
                # endpoint is metadata-only by *shape*, not by filtering (ADR-0026),
                # and an unconstrained operator string echoed from a file is the one
                # way that could stop being true. Reporting the governed subset keeps
                # the claim exact: these are the knobs a caller can set, so these are
                # the knobs a caller is shown.
                parser_options={
                    option: value
                    for option, value in sorted(policy.parser_options.items())
                    if option in OFFERABLE_OPTION_NAMES and isinstance(value, bool)
                },
            )
            for policy in config.columns
        ),
    )

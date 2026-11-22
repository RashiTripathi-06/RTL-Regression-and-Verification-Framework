from __future__ import annotations
import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from .models import (
    STATUS_PASS_REFERENCE_VERIFIED,
    STATUS_FUNCTIONAL_FAIL,
    STATUS_REFERENCE_DISPUTED,
    STATUS_REFERENCE_UNAVAILABLE,
    EXEC_SUCCESS,
    EXEC_SKIPPED,
    VERIF_PASS,
    VERIF_FAIL,
    VERIF_INVALID,
    VERIF_UNCHECKED,
    AUDIT_MATCH,
    AUDIT_MISMATCH,
    AUDIT_SKIPPED
)
from .reference_verifier import ReferenceConfig, ReferenceTiming, ReferenceDataLoader, ParsedVector
from .retriever import ExternalReferenceRetriever, RetrievalResult


class ReferenceCategory:
    DIRECT_IO_TABLE = "direct_io_table"
    DECODING_TABLE = "decoding_table"
    MATHEMATICAL_SPEC = "mathematical_spec"
    DOCUMENTATION = "documentation"
    UNSUPPORTED = "unsupported"


@dataclass
class ReferenceSource:
    name: str
    priority: int = 1  # 1 is primary, 2 is secondary/fallback
    category: str = ReferenceCategory.DIRECT_IO_TABLE
    file_path: Optional[Path] = None
    url: Optional[str] = None
    format: str = "csv"  # "csv", "json", "mem", "hex", "txt", "pdf", "html_table"
    radix: str = "hex"  # "hex", "dec", "bin"
    input_mapping: Dict[str, str] = field(default_factory=dict)
    output_mapping: Dict[str, str] = field(default_factory=dict)
    timing: ReferenceTiming = field(default_factory=ReferenceTiming)
    notes: str = ""
    is_available: bool = False
    file_hash: str = ""
    retrieval_provenance: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.file_path:
            self.file_path = Path(self.file_path)
            if self.file_path.exists():
                self.is_available = True
                try:
                    self.file_hash = hashlib.sha256(self.file_path.read_bytes()).hexdigest()
                except Exception:
                    self.file_hash = ""
            else:
                self.is_available = False
        elif self.url and not self.file_path:
            # URLs without local cached files are treated as remote references until retrieved
            self.is_available = False

    def to_reference_config(self) -> Optional[ReferenceConfig]:
        if not self.file_path or not self.is_available:
            return None
        return ReferenceConfig(
            file=self.file_path,
            format=self.format,
            radix=self.radix,
            input_mapping=dict(self.input_mapping),
            output_mapping=dict(self.output_mapping),
            timing=self.timing,
            file_hash=self.file_hash,
            provenance=dict(self.retrieval_provenance)
        )


class ReferenceClassificationEngine:
    """Classifies external reference materials into generic verification categories."""

    @staticmethod
    def classify(
        file_path: Optional[Path] = None,
        url: Optional[str] = None,
        declared_type: Optional[str] = None
    ) -> str:
        if declared_type:
            dt = declared_type.lower()
            if dt in ("direct_io_table", "lookup_table", "arithmetic_table", "lut", "html_table", "table"):
                return ReferenceCategory.DIRECT_IO_TABLE
            if dt in ("decoding_table", "encoding_table", "decode"):
                return ReferenceCategory.DECODING_TABLE
            if dt in ("mathematical_spec", "spec", "specification", "formula"):
                return ReferenceCategory.MATHEMATICAL_SPEC
            if dt in ("documentation", "datasheet", "pdf", "manual"):
                return ReferenceCategory.DOCUMENTATION

        if file_path:
            p = Path(file_path)
            if not p.exists():
                return ReferenceCategory.UNSUPPORTED

            ext = p.suffix.lower()
            if ext in (".pdf", ".docx", ".doc"):
                return ReferenceCategory.DOCUMENTATION
            if ext in (".md", ".rst", ".tex"):
                return ReferenceCategory.MATHEMATICAL_SPEC

            if ext in (".csv", ".json", ".mem", ".hex", ".dat", ".txt"):
                try:
                    content = p.read_text(encoding="utf-8", errors="replace").strip()
                    lines = [ln.strip() for ln in content.splitlines() if ln.strip() and not ln.strip().startswith("#") and not ln.strip().startswith("//")]
                    if not lines:
                        return ReferenceCategory.UNSUPPORTED

                    # Check CSV headers
                    if ext == ".csv" or ("," in lines[0] and not lines[0].startswith("@")):
                        header_cols = [c.strip().lower() for c in lines[0].split(",")]
                        if len(header_cols) == 2 and any(any(k in c for k in ("val", "real", "float", "dec", "decode")) for c in header_cols):
                            return ReferenceCategory.DECODING_TABLE
                        if len(header_cols) >= 2:
                            return ReferenceCategory.DIRECT_IO_TABLE

                    # Check tabular lines
                    first_tokens = lines[0].split()
                    if len(first_tokens) == 2:
                        try:
                            float(first_tokens[1])
                            return ReferenceCategory.DECODING_TABLE
                        except ValueError:
                            pass

                    if len(first_tokens) > 2:
                        return ReferenceCategory.DIRECT_IO_TABLE
                except Exception:
                    return ReferenceCategory.UNSUPPORTED

        if url:
            u = url.lower()
            if any(k in u for k in ("decode", "lookup", "widget", "converter")):
                return ReferenceCategory.DECODING_TABLE
            if any(k in u for k in ("spec", "standard", "ieee", "doc")):
                return ReferenceCategory.MATHEMATICAL_SPEC
            return ReferenceCategory.DOCUMENTATION

        return ReferenceCategory.UNSUPPORTED


@dataclass
class ReferenceResolutionResult:
    case: str  # "CASE_1_PRIMARY_ACTIVE", "CASE_2_FALLBACK_ACTIVE", "CASE_3_DISPUTED", "CASE_4_UNAVAILABLE"
    active_source: Optional[ReferenceSource] = None
    active_config: Optional[ReferenceConfig] = None
    cross_validation_status: str = "UNCHECKED"  # "MATCH", "DISPUTED", "NOT_APPLICABLE", "UNCHECKED"
    conflicting_vectors: List[Dict[str, Any]] = field(default_factory=list)
    diagnostic: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)


class ReferenceResolver:
    """
    Generic Reference Priority and Resolution Engine.
    Distinguishes Case 1 (Golden primary), Case 2 (Fallback secondary),
    Case 3 (Disputed conflicting sources), and Case 4 (Unavailable).
    """

    @classmethod
    def resolve(cls, config: Dict[str, Any], root_dir: Path) -> ReferenceResolutionResult:
        primary: Optional[ReferenceSource] = None
        secondary: Optional[ReferenceSource] = None
        cache_dir = root_dir / config.get("reference_cache_dir", ".reference_cache")
        offline_global = bool(config.get("offline_reference", False))

        # 1. Parse multi-source configuration schema
        ref_sources = config.get("reference_sources")
        if ref_sources and isinstance(ref_sources, dict):
            for key, src_dict in ref_sources.items():
                if not isinstance(src_dict, dict):
                    continue
                p_prio = int(src_dict.get("priority", 1 if key in ("primary", "golden") else 2))
                raw_path = src_dict.get("path") or src_dict.get("local_path") or src_dict.get("file")
                fpath = (root_dir / raw_path).resolve() if raw_path else None
                if fpath and not fpath.exists():
                    for parent_cand in [root_dir.parent, root_dir.parent.parent]:
                        cand = (parent_cand / raw_path).resolve()
                        if cand.exists():
                            fpath = cand
                            break
                url = src_dict.get("url")
                src_format = src_dict.get("format", "csv")
                retrieval_prov = {}
                file_hash = ""

                if url:
                    is_offline = bool(src_dict.get("offline", offline_global))
                    ret_res = ExternalReferenceRetriever.retrieve(
                        url=url,
                        format=src_format,
                        source_name=src_dict.get("name", key),
                        table_id=src_dict.get("table_id"),
                        table_index=int(src_dict.get("table_index", 0)),
                        cache_dir=cache_dir,
                        offline=is_offline,
                        timeout=float(src_dict.get("timeout_seconds", 15.0))
                    )
                    if ret_res.success:
                        fpath = ret_res.local_file
                        file_hash = ret_res.content_hash
                        src_format = ret_res.format
                        src_dict["local_path"] = str(fpath)
                        retrieval_prov = {
                            "source_url": url,
                            "retrieval_timestamp": ret_res.retrieval_timestamp,
                            "sha256": ret_res.content_hash,
                            "is_cached": ret_res.is_cached,
                            "content_changed": ret_res.content_changed,
                            "metadata": ret_res.metadata
                        }
                    else:
                        retrieval_prov = {
                            "source_url": url,
                            "error": ret_res.error_message
                        }

                cat = ReferenceClassificationEngine.classify(
                    file_path=fpath,
                    url=url,
                    declared_type=src_dict.get("type")
                )

                t_dict = src_dict.get("timing", config.get("reference", {}).get("timing", {}))
                timing = ReferenceTiming(
                    mode=t_dict.get("mode", "combinational"),
                    settling_time_ns=float(t_dict.get("settling_time_ns", 1.0)),
                    clock_signal=t_dict.get("clock"),
                    reset_signal=t_dict.get("reset"),
                    latency_cycles=int(t_dict.get("latency_cycles", 1))
                )

                source_obj = ReferenceSource(
                    name=src_dict.get("name", key),
                    priority=p_prio,
                    category=cat,
                    file_path=fpath,
                    url=url,
                    format=src_format,
                    radix=src_dict.get("radix", "hex"),
                    input_mapping=src_dict.get("input_mapping", config.get("reference", {}).get("input_mapping", {})),
                    output_mapping=src_dict.get("output_mapping", config.get("reference", {}).get("output_mapping", {})),
                    timing=timing,
                    notes=src_dict.get("notes", ""),
                    retrieval_provenance=retrieval_prov
                )
                if file_hash:
                    source_obj.file_hash = file_hash

                if p_prio == 1 and primary is None:
                    primary = source_obj
                elif secondary is None:
                    secondary = source_obj

        # 2. Backward compatibility with legacy "reference" config
        legacy_ref = config.get("reference")
        if primary is None and legacy_ref and isinstance(legacy_ref, dict) and legacy_ref.get("file"):
            lpath = (root_dir / legacy_ref["file"]).resolve()
            if not lpath.exists():
                for parent_cand in [root_dir.parent, root_dir.parent.parent]:
                    cand = (parent_cand / legacy_ref["file"]).resolve()
                    if cand.exists():
                        lpath = cand
                        break
            cat = ReferenceClassificationEngine.classify(file_path=lpath)
            t_dict = legacy_ref.get("timing", {})
            timing = ReferenceTiming(
                mode=t_dict.get("mode", "combinational"),
                settling_time_ns=float(t_dict.get("settling_time_ns", 1.0)),
                clock_signal=t_dict.get("clock"),
                reset_signal=t_dict.get("reset"),
                latency_cycles=int(t_dict.get("latency_cycles", 1))
            )
            primary = ReferenceSource(
                name="legacy_golden",
                priority=1,
                category=cat,
                file_path=lpath,
                format=legacy_ref.get("format", "csv"),
                radix=legacy_ref.get("radix", "hex"),
                input_mapping=dict(legacy_ref.get("input_mapping", {})),
                output_mapping=dict(legacy_ref.get("output_mapping", {})),
                timing=timing
            )

        # 3. Handle Professor Reference declared as top-level key
        prof_ref = config.get("professor_reference")
        if secondary is None and prof_ref and isinstance(prof_ref, dict):
            raw_path = prof_ref.get("local_path") or prof_ref.get("path") or prof_ref.get("file")
            fpath = (root_dir / raw_path).resolve() if raw_path else None
            url = prof_ref.get("url")
            src_format = prof_ref.get("format", "csv")
            retrieval_prov = {}
            file_hash = ""

            if url:
                is_offline = bool(prof_ref.get("offline", offline_global))
                ret_res = ExternalReferenceRetriever.retrieve(
                    url=url,
                    format=src_format,
                    source_name=prof_ref.get("name", "professor_reference"),
                    table_id=prof_ref.get("table_id"),
                    table_index=int(prof_ref.get("table_index", 0)),
                    cache_dir=cache_dir,
                    offline=is_offline,
                    timeout=float(prof_ref.get("timeout_seconds", 15.0))
                )
                if ret_res.success:
                    fpath = ret_res.local_file
                    file_hash = ret_res.content_hash
                    src_format = ret_res.format
                    prof_ref["local_path"] = str(fpath)
                    retrieval_prov = {
                        "source_url": url,
                        "retrieval_timestamp": ret_res.retrieval_timestamp,
                        "sha256": ret_res.content_hash,
                        "is_cached": ret_res.is_cached,
                        "content_changed": ret_res.content_changed,
                        "metadata": ret_res.metadata
                    }
                else:
                    retrieval_prov = {
                        "source_url": url,
                        "error": ret_res.error_message
                    }

            cat = ReferenceClassificationEngine.classify(file_path=fpath, url=url, declared_type=prof_ref.get("type"))
            secondary = ReferenceSource(
                name=prof_ref.get("name", "professor_reference"),
                priority=int(prof_ref.get("priority", 2)),
                category=cat,
                file_path=fpath,
                url=url,
                format=src_format,
                radix=prof_ref.get("radix", "hex"),
                input_mapping=prof_ref.get("input_mapping", {}),
                output_mapping=prof_ref.get("output_mapping", {}),
                notes=prof_ref.get("notes", ""),
                retrieval_provenance=retrieval_prov
            )
            if file_hash:
                secondary.file_hash = file_hash

        # 4. Evaluate Resolution Cases
        # CASE 1: Primary golden reference is available
        if primary and primary.is_available and primary.category == ReferenceCategory.DIRECT_IO_TABLE:
            primary_cfg = primary.to_reference_config()
            xval_status = "NOT_APPLICABLE"
            conflicts: List[Dict[str, Any]] = []

            # Check if secondary allows direct cross-validation
            if secondary and secondary.is_available and secondary.category == ReferenceCategory.DIRECT_IO_TABLE:
                sec_cfg = secondary.to_reference_config()
                if sec_cfg:
                    xval_status, conflicts = cls._cross_validate(primary_cfg, sec_cfg)
                    if xval_status == "DISPUTED":
                        # CASE 3: Conflict between primary and secondary
                        diag = f"Reference conflict detected: Primary '{primary.name}' and Secondary '{secondary.name}' disagree on {len(conflicts)} vectors."
                        return ReferenceResolutionResult(
                            case="CASE_3_DISPUTED",
                            active_source=None,
                            active_config=None,
                            cross_validation_status="DISPUTED",
                            conflicting_vectors=conflicts,
                            diagnostic=diag,
                            provenance={
                                "resolution_case": "CASE_3_DISPUTED",
                                "primary_source": primary.name,
                                "primary_file": str(primary.file_path),
                                "primary_provenance": primary.retrieval_provenance,
                                "secondary_source": secondary.name,
                                "secondary_file": str(secondary.file_path),
                                "secondary_provenance": secondary.retrieval_provenance,
                                "conflict_count": len(conflicts)
                            }
                        )

            return ReferenceResolutionResult(
                case="CASE_1_PRIMARY_ACTIVE",
                active_source=primary,
                active_config=primary_cfg,
                cross_validation_status=xval_status,
                conflicting_vectors=[],
                diagnostic=f"Selected Primary Golden Reference '{primary.name}' for Path B verification.",
                provenance={
                    "resolution_case": "CASE_1_PRIMARY_ACTIVE",
                    "primary_source": primary.name,
                    "primary_file": str(primary.file_path),
                    "primary_hash": primary.file_hash,
                    "primary_provenance": primary.retrieval_provenance,
                    "secondary_source": secondary.name if secondary else None,
                    "secondary_category": secondary.category if secondary else None,
                    "secondary_provenance": secondary.retrieval_provenance if secondary else None,
                    "cross_validation": xval_status
                }
            )

        # CASE 2: Primary is absent, but secondary is available
        if (not primary or not primary.is_available) and secondary and secondary.is_available:
            if secondary.category == ReferenceCategory.DIRECT_IO_TABLE:
                sec_cfg = secondary.to_reference_config()
                return ReferenceResolutionResult(
                    case="CASE_2_FALLBACK_ACTIVE",
                    active_source=secondary,
                    active_config=sec_cfg,
                    cross_validation_status="NOT_APPLICABLE",
                    diagnostic=f"Primary golden reference absent. Using Secondary Reference '{secondary.name}' as fallback.",
                    provenance={
                        "resolution_case": "CASE_2_FALLBACK_ACTIVE",
                        "fallback_source": secondary.name,
                        "fallback_file": str(secondary.file_path),
                        "fallback_hash": secondary.file_hash,
                        "fallback_provenance": secondary.retrieval_provenance
                    }
                )
            else:
                diag = f"Secondary reference '{secondary.name}' is classified as '{secondary.category}' (not direct I/O). Cannot directly drive Path B without an external reference model."
                return ReferenceResolutionResult(
                    case="CASE_4_UNAVAILABLE",
                    active_source=None,
                    active_config=None,
                    cross_validation_status="NOT_APPLICABLE",
                    diagnostic=diag,
                    provenance={
                        "resolution_case": "CASE_4_UNAVAILABLE",
                        "secondary_source": secondary.name,
                        "secondary_category": secondary.category,
                        "secondary_file": str(secondary.file_path) if secondary.file_path else None,
                        "secondary_provenance": secondary.retrieval_provenance,
                        "reason": "Secondary reference cannot establish direct input-output vectors."
                    }
                )

        # CASE 4: Neither source provides usable expected outputs
        reasons = []
        if primary and not primary.is_available:
            if primary.url and primary.retrieval_provenance.get("error"):
                reasons.append(f"Primary URL '{primary.url}' retrieval failed: {primary.retrieval_provenance['error']}")
            elif primary.url:
                reasons.append(f"Primary URL '{primary.url}' has no local cached dataset.")
            elif primary.file_path:
                reasons.append(f"Primary file '{primary.file_path}' not found.")
        if secondary and not secondary.is_available:
            if secondary.url and secondary.retrieval_provenance.get("error"):
                reasons.append(f"Secondary URL '{secondary.url}' retrieval failed: {secondary.retrieval_provenance['error']}")
            elif secondary.url:
                reasons.append(f"Secondary URL '{secondary.url}' has no local cached dataset.")
            elif secondary.file_path:
                reasons.append(f"Secondary file '{secondary.file_path}' not found.")
        diag_str = " | ".join(reasons) if reasons else "No reference sources configured."

        return ReferenceResolutionResult(
            case="CASE_4_UNAVAILABLE",
            active_source=None,
            active_config=None,
            cross_validation_status="NOT_APPLICABLE",
            diagnostic=f"Reference Unavailable: {diag_str}",
            provenance={
                "resolution_case": "CASE_4_UNAVAILABLE",
                "reason": diag_str,
                "primary_source": primary.name if primary else None,
                "primary_provenance": primary.retrieval_provenance if primary else None,
                "secondary_source": secondary.name if secondary else None,
                "secondary_provenance": secondary.retrieval_provenance if secondary else None
            }
        )

    @classmethod
    def _cross_validate(
        cls,
        primary_cfg: ReferenceConfig,
        secondary_cfg: ReferenceConfig
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Compares two direct I/O reference sources for vector-level consensus."""
        try:
            vecs_prim = ReferenceDataLoader.load(primary_cfg)
            vecs_sec = ReferenceDataLoader.load(secondary_cfg)
        except Exception:
            return "UNCHECKED", []

        if not vecs_prim or not vecs_sec:
            return "UNCHECKED", []

        # Index primary vectors by inputs tuple
        prim_map: Dict[Tuple[Tuple[str, int], ...], Dict[str, int]] = {}
        for vp in vecs_prim:
            key = tuple(sorted(vp.inputs.items()))
            prim_map[key] = vp.expected_outputs

        conflicts = []
        compared = 0
        for vs in vecs_sec:
            key = tuple(sorted(vs.inputs.items()))
            if key in prim_map:
                compared += 1
                prim_exp = prim_map[key]
                sec_exp = vs.expected_outputs
                for port, s_val in sec_exp.items():
                    if port in prim_exp and prim_exp[port] != s_val:
                        conflicts.append({
                            "inputs": vs.inputs,
                            "port": port,
                            "primary_expected": f"{prim_exp[port]:x}",
                            "secondary_expected": f"{s_val:x}"
                        })

        if conflicts:
            return "DISPUTED", conflicts
        if compared > 0:
            return "MATCH", []
        return "NOT_APPLICABLE", []

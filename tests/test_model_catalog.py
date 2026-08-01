from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "installer" / "model-catalog.json"


def load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_catalog_has_unique_models_and_packs() -> None:
    catalog = load_catalog()
    model_ids = [model["id"] for model in catalog["models"]]
    pack_ids = [pack["id"] for pack in catalog["packs"]]
    assert len(model_ids) == len(set(model_ids))
    assert len(pack_ids) == len(set(pack_ids))

    known = set(model_ids)
    for pack in catalog["packs"]:
        selected = (
            pack["required_model_ids"]
            + pack["optional_model_ids"]
            + pack["api_model_ids"]
        )
        assert set(selected) <= known
        assert "moss-transcribe-diarize-0.9b" in pack["required_model_ids"]
        assert "ecapa-voxceleb" in pack["required_model_ids"]


def test_resource_tiers_cover_vram_without_brand_dependency() -> None:
    catalog = load_catalog()
    policy = catalog["resource_policy"]
    assert policy["gpu_name_is_diagnostic_only"] is True
    assert policy["single_model_vram_is_not_summed_across_gpus"] is True
    assert policy["electricity_cost_is_excluded"] is True

    tiers = [
        tier
        for tier in catalog["resource_tiers"]
        if tier["id"] != "resource-api-only"
    ]
    tiers.sort(key=lambda tier: tier["min_single_gpu_vram_gb"])
    assert tiers[0]["min_single_gpu_vram_gb"] <= 6
    assert tiers[-1]["max_single_gpu_vram_gb"] >= 1000

    for previous, current in zip(tiers, tiers[1:]):
        assert previous["max_single_gpu_vram_gb"] < current[
            "min_single_gpu_vram_gb"
        ]
        assert (
            current["min_single_gpu_vram_gb"]
            - previous["max_single_gpu_vram_gb"]
            <= 0.2
        )

    for tier in tiers:
        assert tier["recommended_ram_gb"] >= tier["min_ram_gb"]
        assert tier["recommended_free_disk_gb"] >= tier["min_free_disk_gb"]
        assert tier["min_gpu_count"] == 1


def test_resource_tiers_include_portable_and_professional_ranges() -> None:
    catalog = load_catalog()
    deployment_ids = {
        deployment["id"] for deployment in catalog["deployment_classes"]
    }
    assert {"portable", "desktop", "workstation", "server"} <= deployment_ids

    tiers = {tier["id"]: tier for tier in catalog["resource_tiers"]}
    assert tiers["resource-12"]["local_text_ceiling"] == "e4b"
    assert tiers["resource-16"]["local_text_ceiling"] == "12b"
    assert tiers["resource-24"]["local_text_ceiling"] == "26b"
    assert tiers["resource-48-79"]["recommended_ram_gb"] >= 128
    assert tiers["resource-80-plus"]["recommended_ram_gb"] >= 256


def test_target_16gb_profile_does_not_default_to_26b() -> None:
    catalog = load_catalog()
    tiers = {tier["id"]: tier for tier in catalog["resource_tiers"]}
    profile = tiers["resource-16"]
    assert profile["recommended_pack_ids"] == [
        "deepseek-production",
        "local-efficient",
    ]
    assert "local-maximum" not in profile["recommended_pack_ids"]

    models = {model["id"]: model for model in catalog["models"]}
    assert models["gemma4-26b"]["production_status"] == "postponed_on_16gb"
    assert models["gemma4-26b"]["supports_cpu_offload"] is True


def test_research_candidate_cannot_be_selected() -> None:
    catalog = load_catalog()
    candidates = [
        model
        for model in catalog["models"]
        if model["production_status"] == "adapter_required"
    ]
    assert candidates
    assert all(model["selectable"] is False for model in candidates)


def test_production_huggingface_revisions_are_exact_sha40() -> None:
    catalog = load_catalog()
    sha40 = re.compile(r"^[0-9a-f]{40}$")
    checked = 0
    for model in catalog["models"]:
        if not model["provider"].startswith("huggingface"):
            continue
        if model["production_status"] == "adapter_required":
            continue
        revisions = [model["revision"], *model.get("additional_revisions", [])]
        for revision in revisions:
            assert sha40.fullmatch(revision), (
                f"{model['id']} has a non-immutable revision: {revision!r}"
            )
            checked += 1
    assert checked >= 6

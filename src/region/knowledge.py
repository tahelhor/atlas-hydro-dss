"""Curated, source-cited knowledge base on water stress in Béni Mellal–Khénifra.

``data/reference/bmk_knowledge_base.json`` is compiled from press, institutional and academic
sources (see each entry's ``source_ids``). It is validated with the same rigour as API data:
every statement must cite >= 1 known source with a URL and publication date, bilingual text
must be present in both languages, and province references must exist.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from src.region.provinces import PROVINCE_IDS, REFERENCE_DIR

KB_PATH = REFERENCE_DIR / "bmk_knowledge_base.json"

Confidence = Literal["high", "medium", "low"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Bilingual(_Strict):
    """Mixin validator: every ``*_en`` field needs a non-empty ``*_fr`` twin and vice versa."""

    @model_validator(mode="after")
    def _both_languages(self):
        data = self.model_dump()
        for key, value in data.items():
            if key.endswith("_en") and isinstance(value, str):
                twin = key[:-3] + "_fr"
                if twin not in data or not data[twin] or not value:
                    raise ValueError(f"bilingual field '{key[:-3]}' must have non-empty en and fr text")
        return self


class Source(_Strict):
    id: str = Field(pattern=r"^S\d{1,3}$")
    title: str = Field(min_length=5)
    publisher: str
    url: HttpUrl
    published: date
    language: Literal["en", "fr", "ar"]


class Sourced(Bilingual):
    source_ids: list[str] = Field(min_length=1)
    confidence: Confidence = "high"


class KeyFigure(Sourced):
    id: str
    value: float
    unit: str
    as_of: str  # date or period the figure refers to, e.g. "2024-03" or "2018-2024"
    label_en: str
    label_fr: str
    province_id: str | None = None


class Town(Sourced):
    name: str
    lat: float = Field(ge=31.0, le=33.6)
    lon: float = Field(ge=-7.6, le=-4.8)
    province_id: str
    note_en: str
    note_fr: str


class ProvinceProfile(Sourced):
    province_id: str
    population_2024: int = Field(gt=0)
    urban_share_pct: float | None = Field(default=None, ge=0, le=100)
    stress_score: int = Field(ge=1, le=5)  # editorial synthesis of the cited evidence
    supply_en: str
    supply_fr: str
    main_issue_en: str
    main_issue_fr: str


class Problem(Sourced):
    id: str
    category: Literal["daily_life", "agriculture", "environment", "economy"]
    icon: str
    severity: int = Field(ge=1, le=3)
    provinces: list[str] = Field(min_length=1)
    title_en: str
    title_fr: str
    desc_en: str
    desc_fr: str


class RootCause(Sourced):
    id: str
    group: Literal["climate", "overuse", "infrastructure", "governance"]
    icon: str
    title_en: str
    title_fr: str
    desc_en: str
    desc_fr: str
    evidence_en: str
    evidence_fr: str


class Solution(Sourced):
    id: str
    lever: str | None = None  # key of a simulator lever, None = qualitative only
    icon: str
    horizon: Literal["short", "medium", "long"]
    cost: Literal["low", "medium", "high"]
    impact: int = Field(ge=1, le=3)
    title_en: str
    title_fr: str
    desc_en: str
    desc_fr: str
    potential_en: str
    potential_fr: str
    barriers_en: str
    barriers_fr: str


class CitizenStory(Sourced):
    id: str
    province_id: str
    icon: str
    quote_en: str
    quote_fr: str


class KnowledgeBase(_Strict):
    compiled_on: date
    disclaimer_en: str
    disclaimer_fr: str
    sources: list[Source] = Field(min_length=5)
    key_figures: list[KeyFigure]
    provinces: list[ProvinceProfile]
    towns: list[Town]
    problems: list[Problem]
    root_causes: list[RootCause]
    solutions: list[Solution]
    stories: list[CitizenStory]

    @field_validator("sources")
    @classmethod
    def _unique_sources(cls, v: list[Source]) -> list[Source]:
        ids = [s.id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate source ids")
        return v

    @model_validator(mode="after")
    def _referential_integrity(self) -> KnowledgeBase:
        known = {s.id for s in self.sources}
        entries: list[Sourced] = [*self.key_figures, *self.provinces, *self.towns, *self.problems,
                                  *self.root_causes, *self.solutions, *self.stories]
        for e in entries:
            missing = set(e.source_ids) - known
            if missing:
                raise ValueError(f"{type(e).__name__} cites unknown sources {sorted(missing)}")
        refs: list[str] = [p.province_id for p in self.provinces]
        refs += [t.province_id for t in self.towns] + [s.province_id for s in self.stories]
        refs += [pid for p in self.problems for pid in p.provinces if pid != "REGION"]
        refs += [k.province_id for k in self.key_figures if k.province_id]
        bad = set(refs) - set(PROVINCE_IDS)
        if bad:
            raise ValueError(f"unknown province ids {sorted(bad)}")
        if {p.province_id for p in self.provinces} != set(PROVINCE_IDS):
            raise ValueError("a profile is required for each of the 5 provinces")
        for group in (self.problems, self.root_causes, self.solutions, self.key_figures, self.stories):
            ids = [g.id for g in group]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate ids in {type(group[0]).__name__}")
        return self

    def source(self, sid: str) -> Source:
        return next(s for s in self.sources if s.id == sid)

    def figure(self, fid: str) -> KeyFigure:
        return next(k for k in self.key_figures if k.id == fid)


def load_knowledge_base(path: Path = KB_PATH) -> KnowledgeBase:
    with path.open(encoding="utf-8") as f:
        return KnowledgeBase.model_validate(json.load(f))


@lru_cache(maxsize=1)
def knowledge_base() -> KnowledgeBase:
    return load_knowledge_base()

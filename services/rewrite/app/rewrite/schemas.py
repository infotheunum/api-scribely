from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from common.rewrite_body_format import EXPECTED_PARAGRAPH_COUNT, normalize_body_paragraphs, paragraph_count
from common.text_spaces import normalize_plain_spaces
from rewrite_app.prompt.style_guide import BODY_MAX_CHARS, BODY_MIN_CHARS

# Structured contracts the LLM's JSON response is validated against (ТЗ
# §4.20 "жёсткая JSON-схема") — anything that doesn't parse into these
# goes to regenerate/dead-letter, never straight to a Draft.


class ExtractedFactSchema(BaseModel):
    kind: str  # who|what|when|number|quote
    text: str


class EnrichResultSchema(BaseModel):
    facts: list[ExtractedFactSchema] = Field(default_factory=list)
    press_release: bool = False
    regulated: bool = False
    market_sensitive: bool = False
    fact_conflict: bool = False
    fact_conflict_note: str = ""


class SeoPackSchema(BaseModel):
    seo_title: str
    seo_description: str
    slug: str
    og_title: str
    og_description: str
    focus_keyphrase: str
    keywords: list[str] = Field(default_factory=list)


class ImageBriefSchema(BaseModel):
    image_brief: str
    image_mood: str = ""
    image_subjects: list[str] = Field(default_factory=list)
    image_style: str = ""
    image_do_not: list[str] = Field(default_factory=list)
    image_alt: str
    image_caption: str = ""
    image_source_suggestion: str = ""


class TagCandidateSchema(BaseModel):
    slug: str
    name: str


_YO_MAP = str.maketrans({"ё": "е", "Ё": "Е"})


def _no_yo(text: str) -> str:
    return text.translate(_YO_MAP)


class RewriteResultSchema(BaseModel):
    title_en: str = Field(min_length=10)
    body_en: str
    title_ru: str = Field(min_length=10)
    body_ru: str
    title_en_variants: list[str] = Field(default_factory=list)
    title_ru_variants: list[str] = Field(default_factory=list)
    sponsor_flag: bool = False
    press_release_flag: bool = False
    disclaimer_flag: bool = False
    suggested_category_slug: str = ""
    tags: list[TagCandidateSchema] = Field(default_factory=list)
    seo_en: SeoPackSchema
    seo_ru: SeoPackSchema
    image_brief: ImageBriefSchema

    @model_validator(mode="after")
    def _normalize_spaces(self) -> RewriteResultSchema:
        # Same class of fix as ё→е: free models emit em/nbsp/narrow spaces.
        self.title_en = normalize_plain_spaces(self.title_en)
        self.title_ru = normalize_plain_spaces(self.title_ru)
        self.body_en = normalize_plain_spaces(self.body_en)
        self.body_ru = normalize_plain_spaces(self.body_ru)
        self.title_en_variants = [normalize_plain_spaces(t) for t in self.title_en_variants]
        self.title_ru_variants = [normalize_plain_spaces(t) for t in self.title_ru_variants]
        self.seo_en.seo_title = normalize_plain_spaces(self.seo_en.seo_title)
        self.seo_en.seo_description = normalize_plain_spaces(self.seo_en.seo_description)
        self.seo_en.og_title = normalize_plain_spaces(self.seo_en.og_title)
        self.seo_en.og_description = normalize_plain_spaces(self.seo_en.og_description)
        self.seo_en.focus_keyphrase = normalize_plain_spaces(self.seo_en.focus_keyphrase)
        self.seo_en.keywords = [normalize_plain_spaces(k) for k in self.seo_en.keywords]
        self.seo_ru.seo_title = normalize_plain_spaces(self.seo_ru.seo_title)
        self.seo_ru.seo_description = normalize_plain_spaces(self.seo_ru.seo_description)
        self.seo_ru.og_title = normalize_plain_spaces(self.seo_ru.og_title)
        self.seo_ru.og_description = normalize_plain_spaces(self.seo_ru.og_description)
        self.seo_ru.focus_keyphrase = normalize_plain_spaces(self.seo_ru.focus_keyphrase)
        self.seo_ru.keywords = [normalize_plain_spaces(k) for k in self.seo_ru.keywords]
        self.image_brief.image_brief = normalize_plain_spaces(self.image_brief.image_brief)
        self.image_brief.image_alt = normalize_plain_spaces(self.image_brief.image_alt)
        self.image_brief.image_caption = normalize_plain_spaces(self.image_brief.image_caption)
        return self

    @model_validator(mode="after")
    def _normalize_paragraphs(self) -> RewriteResultSchema:
        self.body_en = normalize_body_paragraphs(self.body_en)
        self.body_ru = normalize_body_paragraphs(self.body_ru)
        for field_name, body in (("body_en", self.body_en), ("body_ru", self.body_ru)):
            count = paragraph_count(body)
            if count != EXPECTED_PARAGRAPH_COUNT:
                raise ValueError(
                    f"{field_name} must have exactly {EXPECTED_PARAGRAPH_COUNT} paragraphs "
                    f"(got {count})"
                )
        return self

    @model_validator(mode="after")
    def _enforce_body_length(self) -> RewriteResultSchema:
        for field_name, body in (("body_en", self.body_en), ("body_ru", self.body_ru)):
            length = len(body)
            if length < BODY_MIN_CHARS or length > BODY_MAX_CHARS:
                raise ValueError(
                    f"{field_name} must be {BODY_MIN_CHARS}-{BODY_MAX_CHARS} chars "
                    f"(got {length})"
                )
        return self

    @model_validator(mode="after")
    def _enforce_no_yo(self) -> RewriteResultSchema:
        # Style guide (§ "без «ё»") is a hard rule — free-tier models
        # don't reliably honor it via prompting alone (live-observed:
        # "объёмов", "подчёркивает" slipped through), so it's enforced
        # deterministically here rather than left to model compliance.
        self.title_ru = _no_yo(self.title_ru)
        self.body_ru = _no_yo(self.body_ru)
        self.title_ru_variants = [_no_yo(t) for t in self.title_ru_variants]
        self.seo_ru.seo_title = _no_yo(self.seo_ru.seo_title)
        self.seo_ru.seo_description = _no_yo(self.seo_ru.seo_description)
        self.seo_ru.slug = _no_yo(self.seo_ru.slug)
        self.seo_ru.og_title = _no_yo(self.seo_ru.og_title)
        self.seo_ru.og_description = _no_yo(self.seo_ru.og_description)
        self.seo_ru.focus_keyphrase = _no_yo(self.seo_ru.focus_keyphrase)
        self.seo_ru.keywords = [_no_yo(k) for k in self.seo_ru.keywords]
        return self

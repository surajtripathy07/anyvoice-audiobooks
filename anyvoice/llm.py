"""Speaker attribution + character discovery via an LLM. Provider-agnostic:
LLM_PROVIDER=openai|openrouter|anthropic, LLM_MODEL=<model id>."""
from __future__ import annotations
import json, os
from typing import Literal
from pydantic import BaseModel, Field

EMOTIONS = ["neutral", "happy", "sad", "angry", "afraid", "surprised", "tender", "sarcastic", "urgent", "whisper"]


class Character(BaseModel):
    name: str = Field(description="Canonical full name used consistently across the whole book")
    aliases: list[str] = Field(default_factory=list, description="Other names/titles this character is referred to by")
    gender: Literal["male", "female", "unknown"] = "unknown"
    age: Literal["child", "young", "adult", "elderly", "unknown"] = "unknown"
    description: str = Field(default="", description="One line: role and personality, useful for choosing a voice")


class Line(BaseModel):
    id: int = Field(description="The Q id of the quote")
    speaker: str = Field(description="Canonical character name, or 'Narrator' if the quote is not spoken dialogue")
    emotion: Literal["neutral", "happy", "sad", "angry", "afraid", "surprised", "tender", "sarcastic", "urgent", "whisper"] = "neutral"


AMBIENCES = ["none", "rain", "thunderstorm", "wind", "hearth", "night", "sea", "countryside", "street", "ballroom", "carriage", "forest"]
MOODS = ["none", "tense", "warm", "melancholy", "playful", "romantic"]


class Scene(BaseModel):
    start_para: int = Field(description="The [P<n>] paragraph number where this setting begins (first scene starts at the chapter's first paragraph)")
    ambience: Literal["none", "rain", "thunderstorm", "wind", "hearth", "night", "sea", "countryside", "street", "ballroom", "carriage", "forest"] = "none"
    mood: Literal["none", "tense", "warm", "melancholy", "playful", "romantic"] = "none"


class Attribution(BaseModel):
    characters: list[Character] = Field(description="NEW characters introduced in this chapter, or existing ones whose details you can now improve")
    lines: list[Line] = Field(description="One entry for EVERY [Q<id>] tag in the chapter")
    scenes: list[Scene] = Field(description="Setting changes through the chapter, for subtle background sound. Always at least one entry.")


SYSTEM = """You are the casting director for a full-cast audiobook. You receive one chapter of a book in which every quoted passage is tagged [Q<id>] immediately before it, plus the roster of characters known so far.

Your job:
1. For EVERY tagged quote, decide who speaks it. Use the canonical name from the roster whenever the speaker is a known character (match aliases, titles, nicknames, 'his wife', 'the colonel', etc. to the canonical name). If a quote is not spoken dialogue (a quoted title, a written letter read silently, a phrase in scare-quotes, an inner thought the narrator reports), attribute it to 'Narrator'. A letter being read aloud by a character is spoken by that character.
2. Add any NEW speaking character to `characters` with gender, rough age, and a one-line description. Do not re-list existing roster characters unless you are correcting gender/age/description.
3. Track dialogue turns carefully in long unattributed back-and-forth exchanges: speakers usually alternate, and a paragraph break usually means the speaker changed.
4. Give each line a one-word emotion from the allowed list, defaulting to neutral.
5. Mark the setting for background sound: paragraphs are tagged [P<n>]. Emit a `scenes` entry whenever the physical setting or weather changes, with the paragraph where it starts. Ambience choices: rain, thunderstorm, wind, hearth (indoors by a fire, evening), night (outdoors, crickets), sea, countryside (fields, gardens, a walk), street (town bustle), ballroom (assembly, party, dinner with many guests), carriage (travelling), forest, or none. Use 'none' for ordinary indoor conversation when the text gives no cue — background sound should be rare and earned, never guessed. Mood is for optional music: tense, warm, melancholy, playful, romantic, or none.

Be precise and complete: the `lines` list must contain exactly one entry per [Q<id>] tag, in order."""


def _roster_text(roster: list[dict]) -> str:
    if not roster:
        return "(no characters known yet — this is the first chapter)"
    return "\n".join(f"- {c['name']} ({c.get('gender','?')}, {c.get('age','?')}): {c.get('description','')}"
                     + (f"  aliases: {', '.join(c['aliases'])}" if c.get("aliases") else "") for c in roster)


class LLM:
    def __init__(self):
        self.provider = os.environ.get("LLM_PROVIDER", "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "openai")
        default_model = {"anthropic": "claude-opus-5", "openai": "gpt-5.4-mini", "openrouter": "moonshotai/kimi-k3"}[self.provider]
        self.model = os.environ.get("LLM_MODEL", default_model)
        if self.provider == "anthropic":
            import anthropic
            self.client = anthropic.Anthropic()
        else:
            from openai import OpenAI
            kw = {}
            if self.provider == "openrouter":
                kw = dict(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])
            self.client = OpenAI(**kw)
        self.usage = {"input": 0, "output": 0}

    def attribute(self, book_title: str, chapter_title: str, tagged_text: str, roster: list[dict]) -> Attribution:
        user = (f"Book: {book_title}\nChapter: {chapter_title}\n\nKNOWN CHARACTERS:\n{_roster_text(roster)}\n\n"
                f"CHAPTER TEXT:\n{tagged_text}")
        if self.provider == "anthropic":
            r = self.client.messages.parse(
                model=self.model, max_tokens=16000, system=SYSTEM,
                messages=[{"role": "user", "content": user}],
                output_format=Attribution,
            )
            self.usage["input"] += r.usage.input_tokens; self.usage["output"] += r.usage.output_tokens
            return r.parsed_output
        # OpenAI-compatible (openai / openrouter)
        schema = Attribution.model_json_schema()
        _strictify(schema)
        kwargs = dict(model=self.model,
                      messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                      response_format={"type": "json_schema", "json_schema": {"name": "attribution", "strict": True, "schema": schema}})
        try:
            r = self.client.chat.completions.create(**kwargs, reasoning_effort="low")
        except Exception:
            r = self.client.chat.completions.create(**kwargs)
        if r.usage:
            self.usage["input"] += r.usage.prompt_tokens; self.usage["output"] += r.usage.completion_tokens
        return Attribution.model_validate_json(r.choices[0].message.content)


def _strictify(schema: dict) -> None:
    """OpenAI strict mode: every object needs additionalProperties=false and all keys required."""
    if isinstance(schema, dict):
        if schema.get("type") == "object" and "properties" in schema:
            schema["additionalProperties"] = False
            schema["required"] = list(schema["properties"].keys())
        for v in schema.values():
            _strictify(v)
    elif isinstance(schema, list):
        for v in schema:
            _strictify(v)

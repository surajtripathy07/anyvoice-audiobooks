"""No-LLM fallback attribution: speech-tag regexes + turn alternation + pronoun/gender inference.
Used when no API key works. The LLM path replaces all of this."""
from __future__ import annotations
import re
from collections import Counter, defaultdict
from .segmenter import Unit
from .llm import Attribution, Character, Line

VERBS = r"(?:said|replied|cried|asked|answered|continued|added|observed|returned|exclaimed|whispered|muttered|called|repeated|remarked|declared|inquired|interrupted|shouted|laughed|sighed|began|went on|put in|demanded|urged|protested|murmured|groaned|insisted|agreed|admitted)"
TITLE = r"(?:Mr\.|Mrs\.|Miss|Ms\.|Lady|Sir|Lord|Dr\.|Doctor|Colonel|Captain|Aunt|Uncle|Professor)"
NAME = rf"((?:{TITLE}\s)?[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)"
PRON = r"((?i:she|he|his wife|his lady|her husband|her mother|her father|his mother|his father|the lady|the gentleman))"
AFTER = re.compile(rf"^[,;\s—-]*(?:{VERBS}\s+(?:{NAME}|{PRON})|(?:{NAME}|{PRON})\s+{VERBS})", re.S)
BEFORE = re.compile(rf"(?:(?:{NAME}|{PRON})\s+{VERBS}|{VERBS}\s+(?:{NAME}|{PRON}))[,:;\s—-]*$", re.S)
FEMALE_TITLE = re.compile(r"^(Mrs\.|Miss|Ms\.|Lady|Aunt)(?=\s)")
MALE_TITLE = re.compile(r"^(Mr\.|Sir|Lord|Colonel|Captain|Uncle|Dr\.|Doctor)(?=\s)")
FEMALE_WORDS = {"she", "her", "hers", "herself", "wife", "lady", "mother", "daughter", "sister", "aunt", "girl", "woman", "madam", "miss", "mrs."}
MALE_WORDS = {"he", "him", "his", "himself", "husband", "gentleman", "father", "son", "brother", "uncle", "boy", "man", "sir", "mr."}
FEMALE_NAMES = set("""elizabeth jane lydia kitty mary charlotte maria catherine caroline louisa georgiana anne lizzy eliza emma anna alice
lucy sarah susan margaret helen ellen laura rose grace hannah harriet fanny isabella sophia clara diana dorothy edith eleanor
julia lucia mrs miss lady rachel rebecca ruth victoria abigail agnes amelia beatrice bella cecilia charlotte daisy dora elinor
marianne fanny jo meg amy beth hermione ginny luna molly scarlett melanie daenerys arya sansa catelyn cersei brienne bess nora
alexandra amanda andrea angela ashley barbara brenda carol christine cynthia deborah donna elaine emily erin frances gloria
irene jacqueline janet jennifer jessica joan joyce judith karen katherine kathleen kimberly linda lisa lois marie martha mildred
nancy natalie nicole olivia pamela patricia paula phyllis rosemary sandra sharon shirley stephanie teresa theresa virginia wendy
eowyn galadriel arwen tess bathsheba dorothea maggie becky esther hester cathy nelly isabel""".split())
MALE_NAMES = set("""john james william george charles henry edward thomas richard robert arthur frederick francis fitzwilliam
darcy bingley wickham collins denny gardiner philips lucas hurst forster jack harry ron albus severus sirius remus draco neville
peter paul mark luke matthew andrew philip simon stephen david daniel samuel joseph benjamin michael christopher anthony patrick
oliver jacob ethan noah liam mason logan alexander sebastian nathan caleb adam owen tom tim bill bob jim joe jon ned robb tyrion
jaime jorah sam bran frodo sam gandalf aragorn legolas gimli boromir bilbo pip heathcliff edgar linton hindley lockwood
sherlock watson holmes mycroft lestrade victor jean javert marius gavroche pip joe magwitch herbert wemmick jaggers""".split())


def attribute(units: list[Unit], roster: list[dict]) -> Attribution:
    known = {c["name"]: c for c in roster}
    gender_of = {n: c.get("gender", "unknown") for n, c in known.items()}
    new: dict[str, Character] = {}
    lines: list[tuple[int, str]] = []
    ctx_words: dict[str, Counter] = defaultdict(Counter)   # pronoun evidence per speaker
    recent: list[str] = []
    last_para, para_speaker = -1, None

    def gender_guess(name: str) -> str:
        if FEMALE_TITLE.match(name): return "female"
        if MALE_TITLE.match(name): return "male"
        first = name.split()[0].lower()
        if first in FEMALE_NAMES: return "female"
        if first in MALE_NAMES: return "male"
        return "unknown"

    def by_gender(g: str):
        for s in reversed(recent):
            if gender_of.get(s) == g:
                return s
        return f"Unknown ({g})"

    for i, u in enumerate(units):
        if u.kind != "quote":
            continue
        nxt = units[i + 1] if i + 1 < len(units) and units[i + 1].para == u.para else None
        prv = units[i - 1] if i > 0 and units[i - 1].para == u.para else None
        tag = None
        m = nxt and nxt.kind == "narr" and AFTER.search(nxt.text)
        if not m:
            m = prv and prv.kind == "narr" and BEFORE.search(prv.text[-160:])
        if m:
            tag = next(g for g in m.groups() if g)
        speaker = None
        if tag:
            low = tag.lower()
            if re.fullmatch(PRON, low):
                g = "female" if low in ("she", "his wife", "his lady", "her mother", "his mother", "the lady") else "male"
                speaker = by_gender(g)
            else:
                speaker = _canon(tag, known, new)
        if speaker is None:
            if u.para == last_para and para_speaker:
                speaker = para_speaker
            elif len(recent) >= 2:
                speaker = recent[-2] if recent[-1] == para_speaker else recent[-1]
            elif recent:
                speaker = recent[-1]
            else:
                speaker = "Unknown (unknown)"
        if speaker not in known and speaker not in new:
            g = gender_guess(speaker) if not speaker.startswith("Unknown") else speaker[9:-1]
            new[speaker] = Character(name=speaker, gender=g, age="adult", description="(heuristic)")
            gender_of[speaker] = g
        ctx = ((prv.text if prv else "") + " " + (nxt.text if nxt else "")).lower()
        ctx_words[speaker].update(w for w in re.findall(r"[a-z.]+", ctx) if w in FEMALE_WORDS or w in MALE_WORDS)
        if u.para != last_para:
            last_para, para_speaker = u.para, speaker
        if not recent or recent[-1] != speaker:
            recent.append(speaker); recent = recent[-4:]
        lines.append((u.id, speaker))

    for name, c in new.items():                      # settle unknown genders from pronoun evidence
        if c.gender == "unknown":
            f = sum(v for w, v in ctx_words[name].items() if w in FEMALE_WORDS)
            m = sum(v for w, v in ctx_words[name].items() if w in MALE_WORDS)
            c.gender = "female" if f > m else "male" if m > f else "unknown"
    return Attribution(characters=list(new.values()), lines=[Line(id=i, speaker=s, emotion="neutral") for i, s in lines])


def _canon(name: str, known: dict, new: dict) -> str:
    """'Bennet' -> 'Mr. Bennet' if unique; 'Elizabeth' -> 'Elizabeth Bennet' if unique; else keep."""
    pool = list(known) + list(new)
    if name in pool:
        return name
    parts = name.split()
    hits = [n for n in pool if not n.startswith("Unknown") and (n.split()[-1] == parts[-1] or n.split()[0] == parts[0])]
    return hits[0] if len(hits) == 1 else name

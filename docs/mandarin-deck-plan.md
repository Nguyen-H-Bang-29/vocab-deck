# Mandarin Deck — Reuse Plan

> **⚠ Superseded.** This plan has moved and now evolves in the
> `mandarin_deck` repo itself: `mandarin_deck/docs/mandarin-deck-plan.md`.
> That copy is the live source of truth (leveling §2.5, momentum §2.6,
> popularity §2.7, admin controls §2.8 are all newer than this frozen
> snapshot). This file is left here only as a historical record of the
> plan as originally drafted before the fork existed — do not edit it
> further; edit the copy in `mandarin_deck` instead.

Planning doc for forking `vocab_deck` (GRE/GregMat trainer) into a Mandarin
Chinese vocabulary trainer ("**mandarin_deck**"). Scope: adaptive learning
(SM-2 SRS), context-aware vocabulary (HSK-graded, sense-level), and reading
comprehension (Claude-generated passages using target vocab).

Status: planning only — no code changes yet.

## 1. What carries over unchanged

The v0.6.0 architecture separates *domain-specific enrichment* (thesaurus,
PDF parsing, quiz question shape) from *domain-agnostic infrastructure*
(SRS scheduling, leveling/personalization, session management, progress
tracking, reading-passage generation, dashboard). The infrastructure layer
is language-agnostic and should be reused wholesale:

| Module | Reuse | Why |
|---|---|---|
| `state.py` | as-is | Singleton wiring (`DB_FILE`, `APP_CONFIG`, `vocab_data`, `anthropic_client`) has no English-specific assumptions. |
| `database.py` | as-is + new tables | `init_db`, `apply_progress_delta` (streaks), `app_settings` key/value store are all generic. |
| `services.py` — SM-2 (`sm2_next`) | as-is | Wozniak (1987) SM-2 is language-agnostic; quality scale (1/3/4/5) unchanged. |
| `services.py` — leveling (`build_level_dictionary`, practicing-cap pool) | as-is | Operates on `challenge_history` attempts/accuracy only; no lexical content involved. See README "Leveling & Personalization Algorithm" — same source-of-truth doc pattern should be copied verbatim for the new repo. |
| `routes/progress.py`, `routes/srs.py` | as-is | Generic over "word" as an opaque string key. |
| `routes/challenge.py` — session management (practice-session resume, carousel of incorrect words) | as-is (shape), swap question generator | The session/answer/resume state machine doesn't care what a "question" contains. |
| `routes/passage.py` — caching, cooldown, `words_key` cache table | as-is (structure), swap prompt + tool schema | Exact-match cache-by-word-set and per-user Claude throttle are reusable verbatim. |
| `data_sources.py` `SourceSpec` registry pattern | as-is (pattern) | Same idea: register a spec per data source, keep extraction rules source-specific. |
| Frontend shell (`static/index.html` dashboard, table/pagination/filtering, settings popup, streak/trend panels) | as-is (structure), swap copy | Table-driven word-level UI and projected-progress ETA panel are content-agnostic. |

**Net effect:** the adaptive-learning engine (SRS + leveling + sessions +
dashboard) is a solved problem here and should not be re-architected — only
the *content model* and *question types* change.

## 2. What must change

### 2.1 Content model: `word` → Chinese lexical entry

The GRE model is flat (`word`, `word_type`, `definition`, `synonyms`,
`antonyms`). Mandarin needs a richer, CRS-like "always be explicit about
units" structure:

```python
@dataclass(slots=True, frozen=True)
class HanziEntry:
    simplified: str
    traditional: str | None
    pinyin: str            # tone-marked, e.g. "xué xí"
    pinyin_numeric: str    # "xue2 xi2" — needed for tone-drill matching
    definition_en: str
    hsk_level: int | None  # 1-9 (2021 standard) or None if out-of-list
    pos: str               # part of speech
    example_sentences: list[ExampleSentence]
    radicals: list[str] | None
    stroke_count: int | None
    synonyms: list[str]    # near-synonym hanzi, when available
    antonyms: list[str]
    audio_url: str | None  # TTS or recorded pronunciation
```

```python
@dataclass(slots=True, frozen=True)
class ExampleSentence:
    hanzi: str
    pinyin: str
    translation_en: str
```

Key nuance vs. the English model: **a "word" identity question exists that
doesn't in English** — simplified vs. traditional, and multiple valid
readings for polyphonic characters (多音字, e.g. 得 = dé/děi/de). The level
dictionary and SRS keys should use `simplified` as the canonical key
(matching how `challenge_history.word` is used today), with `traditional`
carried as metadata, not a separate learnable unit — unless the user
explicitly wants a traditional-script track, in which case treat it as a
second `SourceSpec` variant, not a fork of the whole pipeline.

### 2.2 Enrichment source: Merriam-Webster Thesaurus API → CC-CEDICT / HSK lists

`thesaurus.py` (`ThesaurusAPI`, 1,000 req/day free tier) has no Mandarin
equivalent to swap in 1:1. Replacement plan:

- **Primary data**: [CC-CEDICT](https://cc-cedict.org/) (CC BY-SA, plain-text
  dict, ~120k entries: simplified, traditional, pinyin, English glosses).
  Parse once into `data/processed/cedict_enriched.json` — same warm-up
  pattern as `read_vocab.py`, just a different `SourceSpec` (text dict
  instead of PDF).
- **HSK grading**: public HSK 3.0 (2021) or legacy HSK word lists to populate
  `hsk_level`, used as the initial difficulty axis (replaces "no leveling
  signal" gap in the GRE version, which only had accuracy-based leveling).
- **Synonyms/antonyms**: CC-CEDICT doesn't encode these. Either (a) omit
  synonym/antonym challenge types entirely for v1 and lean on the
  Mandarin-specific question types in §2.3, or (b) generate near-synonym
  sets once via Claude during warm-up and cache to JSON (same "enrich once,
  serve from static JSON" philosophy as the current pipeline — no live API
  key needed to run the web app).
- **Audio**: no free Merriam-Webster-equivalent TTS bundled. Cheapest path:
  generate MP3s once during warm-up via any TTS API (or ship without audio
  in v1 and use the Web Speech API `SpeechSynthesis` client-side, zero
  backend cost, lower quality for tone nuance).

This preserves the "warm-up and web are decoupled" contract: once
`cedict_enriched.json` exists, the web app needs no external API key.

### 2.3 Question types: replace synonym/antonym match with tone- and script-aware challenges

`quiz.py`'s `VocabChallenge` (`generate_synonym_match`,
`generate_antonym_match`, 60/40 mix) doesn't transfer — Chinese pedagogy
centers on the **character ↔ sound ↔ meaning** triangle, not lexical
relations. Replacement challenge set:

| Type | Prompt | Why it matters for Mandarin specifically |
|---|---|---|
| `hanzi_to_meaning` | Show 学习, choose English gloss | Baseline recognition (closest analog to existing definition MCQ). |
| `pinyin_to_hanzi` | Show `xué xí`, choose the hanzi | Tests sound→character mapping, which English orthography has no equivalent of. |
| `hanzi_to_pinyin` | Show 学习, choose correct pinyin+tone | **Tone accuracy must be scored separately from character accuracy** — a learner can know the character and consonant/vowel and still miss the tone. Track `tone_correct: bool` distinct from `is_correct` in `challenge_history` (extra column), because tone mastery decays faster than character recognition in practice and the leveling algorithm should be able to weight it. |
| `audio_to_hanzi` | Play TTS, choose hanzi (listening) | Tone is inaudible in romanized text; a listening modality is not optional the way it is for English vocab. |
| `sentence_cloze` | Fill blank in an example sentence with the right hanzi among near-homophone/near-synonym distractors | Reuses `example_sentences` from the CC-CEDICT enrichment; distractors should be same-HSK-level, same-POS near-neighbors for a meaningful test (mirrors how `generate_synonym_match` picks antonyms as plausible distractors). |
| `stroke_order` (stretch) | Trace/animate correct stroke order | Out of scope for v1 API design — requires a JS stroke-order engine client-side (e.g. Hanzi Writer, MIT-licensed) rather than a backend question type; flag as frontend-only feature. |

`generate_daily_challenge`'s type-mix ratio becomes a config knob (like
`PRACTICING_WORD_LIMIT` already is) rather than a hardcoded 60/40 split —
put it in `APP_CONFIG` / `app_settings` from day one, e.g.
`challenge_type_weights: dict[str, float]`.

### 2.4 Reading comprehension: same Claude tool-use pattern, Mandarin prompt + bilingual UI

`routes/passage.py`'s architecture (tool-use forced call, `words_key`
exact-match cache, per-username cooldown, `reading_passages` /
`passage_words` tables) is reusable verbatim. Changes needed:

- Prompt: ask for a short **Mandarin** passage (character count instead of
  word count — CJK text length is measured in characters, not
  space-delimited words; target something like 80-120 characters for
  HSK 3-4 level) that uses the session's target hanzi naturally, plus
  pinyin gloss and English translation alongside it.
- Tool schema: `passage_hanzi`, `passage_pinyin`, `passage_translation`,
  plus the existing 3-question comprehension block — but comprehension
  questions should be answerable in English (testing reading, not writing
  ability) unless the product goal is explicitly production practice.
- Model choice: `claude-haiku-4-5` is fine for generation; no change needed
  there. Cite nothing new — same cost/quality tradeoff as today.
- Frontend: needs a pinyin-toggle affordance (show/hide) since a learner
  should be tested on hanzi-only reading before falling back to pinyin —
  this doesn't exist in the English version because there's no romanization
  layer to toggle.

### 2.5 Leveling algorithm: extend, don't replace

Keep the README "Leveling & Personalization Algorithm" structure
(`not-learned` → `practicing` → `proficient` → `master`, attempts/accuracy
thresholds, practicing-cap pool construction, SRS `quality=5` override) —
it's a solid generic mastery model. Two Mandarin-specific extensions worth
deciding on explicitly before implementation (see open questions):

1. **Tone accuracy as a second axis.** A word could be "proficient" on
   character recognition but still failing tones. Options: (a) fold tone
   correctness into the same `is_correct` boolean (simplest, loses signal),
   or (b) track it as a separate `challenge_history.tone_correct` column
   and require both thresholds for `proficient`/`master` (matches spirit of
   the existing "attempts + accuracy" strictness, more correct
   pedagogically, more complex).
2. **HSK level as an entry-level signal, not just accuracy-derived.** The
   English version has no notion of a word's *intrinsic* difficulty — level
   is purely performance-derived. HSK gives an a-priori difficulty signal
   that could seed which words enter the practicing pool first (e.g. fill
   `not-learned` slots in HSK order rather than arbitrary/random order).
   This only touches pool *ordering*, not the level state machine itself.
3. **Drop the per-word exponential-decay weighting — superseded by
   momentum (§2.6).** The current `services.py` (`_DECAY_HALF_LIFE = 14.0`,
   `build_level_dictionary`) weights each attempt by
   `0.5 ** (age_days / 14)` before computing the accuracy used for level
   classification, so a word's older attempts count for less than recent
   ones — a *per-word*, *local* mechanism for "recent performance matters
   more." Note this is undocumented drift: the README "Leveling &
   Personalization Algorithm" spec (and the CLAUDE.md summary of it) says
   levels come from plain `attempts`/`accuracy`, with no mention of decay
   — the code has quietly grown a second, unspecified accuracy signal
   (`raw_accuracy` for display vs. `decayed_accuracy` for classification)
   that the source-of-truth doc never caught up to.

   Momentum (§2.6) already covers "recent performance matters more," just
   at the *global* level instead — pace reacts to consecutive
   right/wrong across the whole attempt stream, on purpose faster on the
   way down than up. Keeping both mechanisms stacked means a single bad
   patch gets penalized twice through uncoordinated paths (locally via
   decayed accuracy dragging a word back toward `practicing`, globally via
   pace dropping) with no clear pedagogical benefit and a harder-to-reason
   -about interaction. For the Mandarin port:
   - Delete `_DECAY_HALF_LIFE`, the `w_total`/`w_correct` weighted
     accumulation, and `decayed_accuracy` from `build_level_dictionary`.
   - `classify_level_from_history` goes back to taking plain `accuracy`
     (i.e. what's currently exposed as `raw_accuracy`) — one accuracy
     number per word again, not two.
   - Level classification becomes exactly what the README already claims
     it is: `attempts` + plain `accuracy` against the thresholds, nothing
     else. Momentum is the only place recency-of-performance now lives.
   - When this ships, update the README/leveling spec to explicitly state
     "no time-decay; recency sensitivity lives in the momentum spec
     (§2.6)" — closes the drift noted above rather than re-introducing an
     undocumented mechanism a second time.

### 2.6 Adaptive pacing — "Momentum" (Source of Truth)

**This section is the canonical reference for pacing behavior.** It governs
*how fast* material moves, not *whether* a word is mastered — that's still
governed entirely by §2.5 / the README leveling spec (now decay-free per
§2.5.3, since this section takes over recency-sensitivity). The two
systems are orthogonal by design:

- **Level** (`not-learned`/`practicing`/`proficient`/`master`) is *evidence*:
  derived strictly from `challenge_history` attempts/accuracy, never
  touched by pacing.
- **Momentum** (`pace`) is *velocity*: how many new words get introduced,
  how far out reviews get spaced, and how hard the questions get, layered
  on top of level/SM-2 without changing what counts as mastery.

This split exists because it's built for a specific learner profile: prior
Mandarin exposure, rusty rather than zero-knowledge. A pure accuracy-gated
system (the GRE original) treats every learner as starting from zero and
ramps painfully slowly regardless of demonstrated recall speed. Momentum
lets recognized material fly through quickly while still requiring real
evidence (via §2.5) before anything is marked mastered.

#### 1) The attempt stream and momentum streak

Every answered challenge (any word, any type) appends to a per-user
**attempt stream**, ordered by time, independent of session boundaries —
momentum is **not** reset by closing the app or by the calendar-day
boundary that `user_progress.streak` (the existing daily-login streak) uses.
Do not conflate the two: `user_progress.streak` measures *daily attendance*;
momentum's `consecutive_correct`/`consecutive_incorrect` measure *recent
correctness*, and persist across sessions/days on purpose — a learner who
was hot yesterday should still be moving fast today.

From the attempt stream, track two mutually exclusive counters, each reset
by the opposite outcome:

- `consecutive_correct`: answers correct since the last incorrect answer.
- `consecutive_incorrect`: answers incorrect since the last correct answer.

The correctness signal is the same `is_correct` boolean used by §2.5
(character/meaning correctness), not `tone_correct` — see Open Question 6.
Keeping momentum on a single, simple signal is a deliberate YAGNI call: a
second momentum stream for tone accuracy is easy to bolt on later if the
single-signal version proves too coarse, but isn't justified up front.

#### 2) The pace multiplier

Each user has one `pace` value, `PACE_MIN <= pace <= PACE_MAX`, default
`PACE_DEFAULT`. It updates on every answer, **asymmetrically** — dropping
faster than it climbs. This is intentional, not just a safe default: on
4-choice MCQ, a 25% baseline guess rate means short correct runs are cheap
to luck into, so upward moves should be conservative; consecutive misses,
by contrast, are a strong and fast signal that the current pace is too
aggressive, so downward moves should react quickly to protect against
frustration/burnout.

```
on correct answer:
    consecutive_correct += 1
    consecutive_incorrect = 0
    if consecutive_correct % STREAK_UP_THRESHOLD == 0:
        pace = min(PACE_MAX, pace + PACE_STEP_UP)

on incorrect answer:
    consecutive_incorrect += 1
    consecutive_correct = 0
    if consecutive_incorrect % STREAK_DOWN_THRESHOLD == 0:
        pace = max(PACE_MIN, pace - PACE_STEP_DOWN)
```

Default parameters (all runtime-configurable, same `app_settings`
mechanism as the existing leveling knobs):

| Parameter | Default | Meaning |
|---|---|---|
| `pace_min` | 0.6 | Slowest allowed pace (heavy reinforcement mode). |
| `pace_max` | 1.8 | Fastest allowed pace (fast-forward mode). |
| `pace_default` | 1.0 | Starting/neutral pace. |
| `streak_up_threshold` | 5 | Consecutive correct answers needed to earn one pace step up. |
| `streak_down_threshold` | 2 | Consecutive incorrect answers needed to trigger one pace step down. |
| `pace_step_up` | 0.05 | Pace increase per up-trigger. |
| `pace_step_down` | 0.15 | Pace decrease per down-trigger (3x steeper than up, by default). |

Validation rules (checked in `POST /api/settings`, same pattern as the
existing `min_attempts_master >= min_attempts_proficient` check):
- `pace_min < pace_default < pace_max`
- `pace_step_down >= pace_step_up`
- `streak_down_threshold <= streak_up_threshold`

**Worked example** (defaults above, starting `pace = 1.0`):

| Event | consecutive_correct | consecutive_incorrect | pace |
|---|---|---|---|
| start | 0 | 0 | 1.00 |
| 5 correct in a row | 5 | 0 | 1.05 |
| 5 more correct | 10 | 0 | 1.10 |
| 2 incorrect in a row | 0 | 2 | 0.95 |
| 1 correct | 1 | 0 | 0.95 |
| 2 incorrect in a row | 0 | 2 | 0.80 |
| 2 more incorrect | 0 | 4 | 0.65 |

A rough patch of 6 misses (three down-triggers) erases more than a full
streak-up cycle of 15 correct answers — reflecting the asymmetric intent
above.

#### 3) What pace actually controls

Pace is a **multiplier layered on top of** existing mechanisms — it never
replaces SM-2's per-word math or the §2.5 level state machine, only scales
their inputs/outputs:

1. **New-word intake (`PRACTICING_WORD_LIMIT` / X).** Effective cap per
   §2 step 2 (fill `not-learned` slots up to X) becomes:
   ```
   X_effective = max(current_practicing_count, round(X_base * pace))
   ```
   The `max(...)` clamp is load-bearing: a pace drop must never *evict*
   words already in the practicing pool, only slow the rate of *new*
   admissions. Momentum controls the on-ramp, not forced removal.

2. **Session length (`daily_questions`).** `round(daily_questions_base *
   pace)`, clamped to `[daily_questions_min, daily_questions_max]` (e.g.
   5–40) so a bad patch never shrinks a session to near-nothing and a hot
   streak never balloons it past a sane length.

3. **SRS review spacing.** After SM-2 (`sm2_next`) computes its own
   `interval_days` from the word's individual EF/repetitions — unchanged —
   apply pace as a final global scalar:
   ```
   interval_days_effective = max(1, round(interval_days_sm2 * pace))
   ```
   High pace pushes well-known material further out (less time
   re-confirming things already retained from before); low pace pulls
   reviews closer in (more reinforcement while things are shaky). The
   `max(1, ...)` floor matches SM-2's own minimum-interval convention.

4. **Challenge difficulty mix (`challenge_type_weights`).** At high pace,
   shift weight toward harder subtypes (tone drills, cloze, listening) and
   away from easy recognition MCQ; at low pace, shift back toward
   recognition-only to rebuild confidence before reintroducing production
   tasks. Exact weight curve is an implementation detail, not part of this
   spec — only the direction (harder-at-high-pace, easier-at-low-pace) is
   canonical.

5. **New-word ordering within HSK bands.** At high pace, sample slightly
   ahead of strict HSK sequence (lets a rusty-but-experienced learner skip
   past material they plausibly already know rather than grinding it in
   order); at low pace, stay strictly sequential/narrow. This only affects
   which `not-learned` words are *offered* first — it never lets a word
   skip the §2.5 evidence requirements to become `proficient`/`master`.

Momentum never overrides the `srs_mastered` exclusion (§1b of the leveling
spec) — a word explicitly rated "Easy" stays excluded from the pool
regardless of pace.

#### 4) Returning-learner calibration (optional, not required for v1)

Because the target learner has prior exposure rather than zero knowledge, a
first-run **placement pass** is worth considering: a short initial batch
sampling across multiple HSK levels (instead of starting at HSK 1) to seed
`pace` above default (e.g. `1.3`) as an optimistic prior. This prior is
self-correcting — the steeper down-step in §2.6.2 will pull it back quickly
if the initial optimism was wrong — so it's a UX nicety (skip the boring
on-ramp), not a correctness risk. Scope as a stretch feature; the core
momentum mechanism works fine without it, just starting flatter at
`pace_default = 1.0`.

#### 5) Storage

```sql
CREATE TABLE IF NOT EXISTS user_momentum (
    username TEXT PRIMARY KEY,
    pace REAL NOT NULL DEFAULT 1.0,
    consecutive_correct INTEGER NOT NULL DEFAULT 0,
    consecutive_incorrect INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Updated in the same code path as `apply_progress_delta` (i.e. wherever an
answer is currently recorded to `challenge_history` — `POST /api/validate`
/ `POST /api/update-progress` / `POST /api/practice-session/<id>/answer`),
so momentum never drifts out of sync with the history it's derived from.

Surface `pace` (and the two streak counters) on `GET
/api/dashboard/<username>` alongside the existing `level_dict`/
`level_policy` payload — worth seeing "moving at 1.4x" as direct feedback,
given the whole point is a learner-visible response to performance.

#### 6) Future modification rule

Same convention as §2.5 / the README leveling spec: if pacing behavior
changes, update this section first, then code/tests. Treat it as source of
truth for future agents and maintainers, on equal footing with the
leveling spec it deliberately stays orthogonal to.

## 3. Proposed module mapping

```
vocab_deck/                     mandarin_deck/
├── vocab_deck/
│   ├── data_sources.py    →    ├── mandarin_deck/
│   ├── read_vocab.py      →    │   ├── data_sources.py     (SourceSpec: cedict, hsk_list)
│   ├── thesaurus.py       →    │   ├── cedict_source.py    (CC-CEDICT parser, replaces thesaurus.py)
│   └── quiz.py            →    │   └── quiz.py             (new challenge types, §2.3)
├── routes/
│   ├── pages.py           →    ├── routes/pages.py         (unchanged)
│   ├── settings.py        →    │   ├── settings.py         (+ challenge_type_weights, tone thresholds)
│   ├── challenge.py       →    │   ├── challenge.py        (swap generator calls, keep session state)
│   ├── progress.py        →    │   ├── progress.py         (unchanged)
│   ├── srs.py             →    │   ├── srs.py              (unchanged)
│   └── passage.py         →    │   └── passage.py          (Mandarin prompt/tool schema, §2.4)
├── database.py             →    ├── database.py             (+ tone_correct col, + hsk_level, + user_momentum table)
├── services.py              →    ├── services.py            (unchanged SM-2/leveling core + HSK ordering hook + momentum engine, §2.6)
├── state.py                  →    ├── state.py                (unchanged)
└── static/                    →    └── static/                 (hanzi/pinyin rendering, stroke-order lib, audio player)
```

## 4. Database schema deltas

Additive only — same migration style as the existing idempotent
`ALTER TABLE ... ADD COLUMN` try/except in `database.py`:

```sql
ALTER TABLE challenge_history ADD COLUMN tone_correct BOOLEAN;
ALTER TABLE challenge_history ADD COLUMN challenge_subtype TEXT;  -- 'pinyin_to_hanzi', 'audio_to_hanzi', ...

-- adaptive pacing, §2.6.5 — one row per user, updated on every answer
CREATE TABLE IF NOT EXISTS user_momentum (
    username TEXT PRIMARY KEY,
    pace REAL NOT NULL DEFAULT 1.0,
    consecutive_correct INTEGER NOT NULL DEFAULT 0,
    consecutive_incorrect INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- new: word metadata not derivable from history (mirrors read-only vocab_data.json for GRE)
-- if kept in DB rather than JSON, otherwise this lives in cedict_enriched.json only
```

`reading_passages` / `passage_words` need no schema change — `words_key`
already works on any string set; just store hanzi instead of English words.

## 5. Frontend deltas

- Font stack: needs a CJK-capable font declared explicitly (system fallback
  chains often don't cover simplified Chinese well cross-platform) —
  violates the "max two font families" web-performance rule unless the CJK
  font is treated as the single required family for hanzi content, with
  Latin text falling back to it too.
- Pinyin toggle (show/hide diacritics) on every hanzi display surface —
  word cards, dashboard table, reading passage.
- Optional stroke-order widget (Hanzi Writer, canvas-based, MIT license) —
  purely client-side, no backend involvement; scope as a stretch feature,
  not part of the v1 API surface.
- Audio playback control wherever a word/sentence is shown, wired to
  `audio_url` (pre-generated) or Web Speech API fallback (§2.2).

## 6. Open questions (need a decision before implementation starts)

1. **Simplified-only, or simplified + traditional as parallel tracks?**
   Affects whether `traditional` is metadata-only (recommended default) or
   a second learnable key.
2. **Tone accuracy: fold into `is_correct`, or track as a separate signal
   feeding a second leveling axis?** (§2.5.1) — recommend separate signal;
   changes `challenge_history` schema and the leveling README spec.
3. **Audio sourcing**: pre-generated TTS at warm-up time (costs API calls,
   consistent quality, works offline) vs. client-side Web Speech API
   (free, zero backend work, quality varies by browser/OS)?
4. **HSK standard**: 2021 HSK 3.0 (9 levels, current official standard) vs.
   legacy HSK (6 levels, still what most existing word lists/frequency data
   are tagged with)? Affects which public word list to source and how
   `hsk_level` int range is validated.
5. **Repo strategy**: new sibling repo (`mandarin_deck`) sharing no code, a
   git fork, or a shared internal package for the infra layer (§1) with
   per-domain plugins for content (§2)? The clean boundary in §1 vs §2
   suggests a shared-package split is viable if more language decks are
   planned beyond Mandarin — but that's speculative generality (YAGNI) if
   this is a one-off fork.
6. **Momentum's correctness signal** (§2.6.1): drive `consecutive_correct`/
   `consecutive_incorrect` off `is_correct` alone (recommended default,
   simplest), or a blend that also penalizes tone misses once
   `tone_correct` exists (§6.2)? Only relevant once tone tracking (open
   question 2) is decided — keep momentum on `is_correct` alone until
   tone tracking ships, then revisit.

## 7. Suggested build order

1. Fork repo skeleton; strip `thesaurus.py`/`quiz.py` synonym-antonym logic;
   keep everything in §1 as-is.
2. CC-CEDICT + HSK list ingestion → `cedict_enriched.json` (new warm-up
   `SourceSpec`), no web app changes yet.
3. New `quiz.py` challenge types (§2.3) against the enriched JSON, unit
   tests per type (mirrors `tests/test_endpoints.py` stub-state pattern).
4. Schema migration (`tone_correct`, `challenge_subtype`, `user_momentum`)
   + remove the `_DECAY_HALF_LIFE` weighting from `build_level_dictionary`
   per §2.5.3 + leveling README update reflecting decisions from
   §6.1-6.2 — **update the README/§2.6 spec before code**, per the
   existing project's own "Future modification rule" (now applies to both
   the leveling spec and §2.6 momentum spec).
5. Momentum engine (§2.6): `user_momentum` read/update hooked into the
   existing answer-recording path (`POST /api/validate` /
   `/api/update-progress` / `/api/practice-session/<id>/answer`), then wire
   `pace` into `PRACTICING_WORD_LIMIT`, `daily_questions`, and the SM-2
   interval post-scaling step — build and test this in isolation from the
   Mandarin-specific content changes (steps 2-3), since it's pure
   infrastructure and can be validated against the existing English data
   first if that's faster to iterate on.
6. `routes/passage.py` Mandarin prompt/tool schema swap.
7. Frontend: CJK font, pinyin toggle, audio control, momentum/pace
   indicator on the dashboard; stroke-order widget deferred to a later
   milestone.
8. Playwright UI tests (`tests/test_ui.py` pattern) for hanzi rendering and
   pinyin toggle specifically — visual regression matters more here than in
   the Latin-script version (rules/web/testing.md priority order already
   puts visual regression first).

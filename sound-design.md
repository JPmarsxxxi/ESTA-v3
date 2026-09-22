# Sound Design Principles

Grounded reference for how ESTA mixes a video's audio, so the sound supports the
edit instead of fighting it. Companion to `editing-principles.md` (picture). The
picture↔sound *seam* (J/L cuts, cut-on-beat) lives in the editing doc; this doc
owns the **mix** — levels, ducking, fades, silence, ambience, SFX.

**How this is used (intended):**
- `render` enforces the codifiable rules on the **Voice / Music / Ambience**
  tracks it builds (per-clip `volume`, `gain_db` already exist in the schema).
- `audio` (found-fetch / assemble) and `plan` reason with the judgment principles.
- **Style- AND format-parameterized** (§3): music-forward montage vs
  narration-forward explainer, and vertical/social vs horizontal/desktop, apply
  these very differently (drives loudness target, ducking depth, mix balance).

---

## 0. The master hierarchy — intelligibility first

The mix has a strict priority. When elements compete for the same space, the
higher one wins; everything below makes room for it.

| # | Layer | Role |
|---|---|---|
| 1 | **Voice / Dialogue** | King. Must always be clear and intelligible. |
| 2 | **SFX / accents** | Punctuate key moments — clear and precise, then gone. |
| 3 | **Music** | Supports mood/energy — sits *under* the voice. |
| 4 | **Ambience** | Foundational bed — "felt, not heard," quietest layer. |

"Ambience should sit quietly beneath dialogue. Spot effects should be clear and
precise. No single element should overpower the others." Source:
[Fiveable — Soundtrack elements](https://fiveable.me/sound-design/unit-1/key-elements-soundtrack-dialogue-music-sound-effects/study-guide/BYtrYAWpJBIRX5ia),
[SFX Engine](https://sfxengine.com/blog/what-is-sound-design).

---

## 1. Deterministic rules — `render` enforces these

### S1 — Loudness target + true-peak ceiling
Normalize the final mix to a platform target; cap true peak at **−1 dBTP**.
- **Driven by `orientation`** (proxy for platform): vertical/social ≈ **−12 LUFS**
  (TikTok/Reels run hot — note: those targets are *unofficial estimates*, not
  published); horizontal/desktop ≈ **−14 LUFS** (YouTube). Square defaults to
  vertical's target.
- Source: [Youlean loudness table](https://youlean.co/loudness-standards-full-comparison-table/),
  [Critical Listening Lab](https://www.criticallisteninglab.com/en/learn/loudness/social-media),
  [Dan Murtagh LUFS](https://danmurtagh.com/lufs-loudness-standards/).

### S2 — Duck music under voice
Whenever Voice is active, pull Music (and Ambience) down to make room; restore in
the gaps. **Depth is intent-based** (§3):
- Music-forward (montage, sparse VO): subtle duck **~3–6 dB** — music stays present.
- Narration-forward (explainer): deep duck **~12–18 dB** — voice clearly dominant.
- Tune attack/release to avoid audible pumping.
- Source: [Gearspace ducking](https://gearspace.com/board/post-production-forum/1198509-ducking-music-under-dialog-your-thoughts-philosophy.html),
  [Adobe auto-duck](https://blog.adobe.com/en/publish/2017/11/02/audition-deep-dive-auto-ducking-music).

### S3 — Fades everywhere (the anti-click / anti-staccato rule)
Never hard-cut audio. A cut off a zero-crossing clicks/pops; the abrupt level
jump is audio's version of jarring.
- Tiny fade (~1 frame) on every audio edit in/out.
- Crossfade (~2 frames) between adjacent clips on the same track.
- Music: deliberate **fade-in / fade-out** at entrances/exits — never a hard start/stop.
- Prefer edit points at **zero crossings**.
- Source: [Electronic Production — fades](https://www.electronicproduction.co.uk/post/audio-fades-the-key-to-clean-seamless-edits),
  [Sound on Sound](https://www.soundonsound.com/techniques/using-fades-crossfades).

### S4 — Speech clarity (weighted by playback)
Compress voice for consistent, always-audible levels (≈ 4:1–6:1 — harder than
podcast). **Vertical/social leans hardest on this**: phone speakers have little
below ~200 Hz, so **midrange clarity beats any LUFS number.** Horizontal/desktop
playback has real low end, so the compression can ease off and the mix can carry
more body. Source:
[OpusClip normalizers](https://www.opus.pro/blog/best-loudness-normalizers).

### S5 — Track level hierarchy
Set static track gains to encode §0: Voice at target, Music well under, Ambience
quietest. This is the floor; S2 ducking automates on top.

---

## 2. Judgment principles — `audio` / `plan` reason with these

### J1 — Silence as punctuation
Don't fill every second. Strategic near-silence focuses the viewer and hits
harder than any effect — especially before a turn or a CTA. Source:
[LBB — story with sound](https://lbbonline.com/news/how-to-tell-a-story-with-sound-design).

### J2 — Ambience felt, not heard
A bed establishes place/mood *before* anything happens, but never asks for
attention. Use it to set the floor, not to be noticed. Source:
[FilmLocal — ambient sound](https://filmlocal.com/filmmaking/master-ambient-sound/).

### J3 — SFX punctuate, don't clutter
Spot effects emphasize key moments/transitions (whoosh on a cut, pop on a text
hit) — precise, then gone. Layer for richness, but nothing overpowers the voice.
Style-gated (a dreamy montage uses few; a punchy explainer uses more). Source:
[Fiveable](https://fiveable.me/sound-design/unit-1/key-elements-soundtrack-dialogue-music-sound-effects/study-guide/BYtrYAWpJBIRX5ia).

### J4 — Sound carries the emotion
Audio does much of the emotional lifting subconsciously. Music/ambience choice
sets tense/lonely/joyful before the picture confirms it — match it to the
script's arc (ties to `editing-principles.md` §0 Emotion). Source:
[SFX Engine](https://sfxengine.com/blog/what-is-sound-design).

---

## 3. Style + format parameterization

Two input sources set the dials.

**Style** (`style-analysis` + requirements mood):

| signal | drives |
|---|---|
| music-forward vs narration-forward | duck depth (S2), bed level (S5) |
| energy | SFX density (J3), music intensity, fade lengths |
| mood (dreamy ↔ punchy) | how much silence (J1), ambience prominence (J2) |

**Format** (`requirements.json` → `orientation`):

| signal | drives |
|---|---|
| vertical / social | hotter loudness target ~−12 LUFS (S1), harder speech compression (S4) |
| horizontal / desktop | ~−14 LUFS (S1), eased compression, more low-end body (S4) |

`feels-over-facts` **vertical** montage → music-forward, light ducking, ambience
prominent, generous silence, few SFX, hot mix. **Horizontal** retention explainer
→ narration-forward, deep ducking, voice king, punchy SFX, −14 LUFS with body.

---

## 4. Maps to ESTA render machinery

| Track (render) | Rules that apply |
|---|---|
| **Voice** (`audio.wav` / spine) | S1 loudness, S4 clarity, §0 priority 1 |
| **Music** | S2 ducking, S3 fades in/out, S5 level |
| **Ambience** | J2 bed, S5 quietest, S3 fades |

The found-audio path already carries `gain_db` per arrangement clip → that's where
S2/S5 levels land. Voice-only (standard-VO) sessions leave Music/Ambience empty
for the user, so these rules mostly engage on found-audio collages and any video
with a music bed.

---

## Sources
- Loudness/LUFS for social — Youlean, Critical Listening Lab, Dan Murtagh, OpusClip
- Ducking / sidechain — Gearspace, Adobe Audition
- Fades / crossfades / clicks — Electronic Production, Sound on Sound
- Sound design / silence / ambience / SFX — Fiveable, SFX Engine, FilmLocal, LBB

# PARITY

Every feature of v2's editor (`apps/studio`, on the `@openreel/core` engine) and where it lives in v3. Status:

- **native**: v3 already has it, in OpenCut itself or in what M1–M3 built.
- **port**: to build in v3. Priority: **P1** = ESTA's own output needs it (render emits it, or the look of every video depends on it); **P2** = regular editing polish; **P3** = occasional.
- **dropped**: not carried over, decided by SPEC.md's non-goals. Every other proposed drop was moved to port P3 by the user.

A port row is ticked when a manual check in the editor passes.

## Timeline and editing

| v2 feature (source) | Status | v3 / plan |
|---|---|---|
| Multi-track timeline: move, trim, split, ripple, snapping (`Timeline`, `timeline/*`) | native | OpenCut timeline |
| Clip context menu: split, duplicate, copy/paste, delete (`ClipContextMenu`, `GraphicsClipContextMenu`) | native | OpenCut context menu and shortcuts |
| Keyframes and easing curves (`KeyframesSection`, `KeyframeEditorPanel`, `KeyframeTrack`, `EasingCurve`) | native | OpenCut keyframes and graph editor (bezier) |
| Markers (`MarkersPanel`, `MarkerIndicator`) | native | OpenCut bookmarks (note, colour, duration) |
| Scene navigator: jump between marker-bounded sections (`SceneNavigatorPanel`) | native | Bookmarks plus v3's shared shot selection (planner, shot strip, timeline) |
| Nested sequences (`NestedSequenceSection`) | native | OpenCut scenes |
| Undo/redo | native | OpenCut command history |
| History list (`HistoryPanel`) | [ ] port P3 | A panel listing the undo stack; click to jump back |
| Track mute/hide (`TrackHeader`) | native | OpenCut track header |
| Track lock (`TrackHeader`) | [ ] port P3 | OpenCut has no lock |
| Beat detection and beat-synced cuts (`BeatSyncSection`, `BeatMarkerOverlay`, `beat-sync-bridge`) | [ ] port P2 | Detect beats on a music clip, show them as markers, snap cuts to them |
| Multi-camera editing (`MultiCameraPanel`) | [ ] port P3 | Kept at the user's request (2026-09-26) rather than dropped. Not used by the pipeline today: Angle switching between synced cameras. ESTA videos are VO over stock and generated footage; no multi-cam source exists in the pipeline. |
| Search (`SearchModal`) | [ ] port P3 | Search media, clips and commands |
| Keyboard shortcuts overlay (`KeyboardShortcutsOverlay`) | native | OpenCut shortcuts help |

## Transform, motion and compositing

| v2 feature (source) | Status | v3 / plan |
|---|---|---|
| Transform: position, scale, rotation (`InspectorPanel`) | native | OpenCut Transform section |
| Alignment to canvas (`AlignmentSection`) | [ ] port P2 | Align left/centre/right/top/middle/bottom buttons |
| Crop (`CropSection`, `CropModeView`) | [ ] port P2 | Crop edges per clip (OpenCut only has masks) |
| Blend modes and opacity (`BlendingSection`) | native | OpenCut Blending section |
| Masks (`MaskSection`) | native | OpenCut masks: 9 shapes plus freeform |
| Composite shot layouts: render's per-clip `transform` for multi-panel shots | [x] port P1 | Done: the transform is carried through and mapped to OpenCut position/scale, so panels sit where render put them. Render's cover fit comes with it, so landscape stock fills a vertical frame |
| Motion presets: Ken Burns, zoom, pan, shake (`MotionPresetsPanel`, `motion-presets`) | [ ] port P2 | One-click keyframe presets. Render's own Ken Burns and zoom already arrive as keyframes |
| Emphasis animations: pulse, shake, pop (`EmphasisAnimationSection`) | [ ] port P2 | Keyframe presets on a clip |
| Motion path editing on the canvas (`MotionPathSection`, `MotionPathHandles`, `MotionPathOverlay`) | [ ] port P3 | Position keyframes work today; this adds dragging the path in the preview |
| Picture-in-picture presets (`PiPSection`) | [ ] port P3 | Corner/size presets over Transform |
| 3D transform: rotation X/Y (`Transform3DSection`, `threejs-layer-renderer`) | [ ] port P3 | Kept at the user's request (2026-09-26) rather than dropped. Not used by the pipeline today: Needs a 3D renderer layer in OpenCut's compositor. Motion graphics now come from HyperFrames, which does 3D itself. |
| Aspect ratio mismatch dialog: fit/fill/stretch (`AspectRatioMatchDialog`) | [ ] port P3 | Prompt when a source doesn't match the canvas |
| Auto reframe: ML subject tracking to change aspect (`AutoReframeSection`) | [ ] port P3 | Kept at the user's request (2026-09-26) rather than dropped. Not used by the pipeline today: Render already builds the timeline at the target orientation; reframing a finished video isn't in ESTA's flow. |
| Motion tracking (`MotionTrackingSection`, `motion-tracking-bridge`) | [ ] port P3 | Kept at the user's request (2026-09-26) rather than dropped. Not used by the pipeline today: Heavy computer vision; nothing in the pipeline pins elements to moving objects. |
| Particle effects (`ParticleEffectsSection`, `ParticleRenderer`) | [ ] port P3 | Kept at the user's request (2026-09-26) rather than dropped. Not used by the pipeline today: Three.js particle layer; HyperFrames motion graphics cover animated overlays. |

## Transitions

| v2 feature (source) | Status | v3 / plan |
|---|---|---|
| Crossfade between clips (render's `transitions`) | native | Render's crossfades arrive as editable crossfades in the Transitions tab (see below) |
| Clip transitions: crossfade, dip to black/white, wipe, slide, zoom, push (`ClipTransitionSection`, `TransitionInspector`, `transition-bridge`) | [x] port P1 | Done: OpenCut's Transitions tab lists every cut; crossfade, dip to black, slide and push, with a length, undoable. Built from overlapping lanes plus tagged keyframes. Checked on rendered frames (dip reaches black at the cut, push is half and half at its midpoint). Dip to white, wipe and zoom remain (P2) |

## Colour and effects

| v2 feature (source) | Status | v3 / plan |
|---|---|---|
| Blur | native | OpenCut effects (its only effect) |
| Basic colour: brightness, contrast, saturation, hue (`VideoEffectsSection`) | [ ] port P1 | Built: a Color effect in the Effects tab, on a new `color-adjust` shader in the rebuilt wasm. Shader verified on known pixels; the in-editor check waits for a browser with a real GPU (this sandbox can't upload frames to WebGPU) |
| Other video effects: vignette, film grain, glow, shadow, chromatic aberration, motion/radial blur (`VideoEffectsSection`) | [ ] port P2 | As OpenCut effect definitions |
| Colour grading: wheels, curves, HSL (`ColorGradingSection`, `ColorWheelsControl`, `CurvesEditor`, `HSLControls`) | [ ] port P2 | |
| LUTs (`LUTLoader`) | [ ] port P2 | Load a .cube LUT as an effect |
| Filter presets (`FilterPresetsPanel`) | [ ] port P2 | Saved combinations of the effects above |
| Adjustment layer (`AdjustmentLayerSection`) | native | OpenCut effect tracks apply to the layers below (its Adjustment tab is a stub; effects are added from the Effects tab) |
| Green screen / chroma key (`GreenScreenSection`) | [ ] port P3 | |
| Background removal, ML (`BackgroundRemovalSection`) | [ ] port P3 | Kept at the user's request (2026-09-26) rather than dropped. Not used by the pipeline today: Needs a segmentation model in the browser; no stage in the pipeline produces cut-out subjects. |
| Photo retouching brush (`RetouchingSection`) | [ ] port P3 | Kept at the user's request (2026-09-26) rather than dropped. Not used by the pipeline today: Photo editing, not video; stills come from stock and get Ken Burns. |
| Photo layers (`PhotoLayersSection`, `photo-bridge`) | [ ] port P3 | Kept at the user's request (2026-09-26) rather than dropped. Not used by the pipeline today: Same: a layered photo editor inside the video editor. |
| Scopes: waveform, vectorscope, histogram (`ScopesPanel`) | [ ] port P3 | |

## Text and captions

| v2 feature (source) | Status | v3 / plan |
|---|---|---|
| Text: font, size, colour, alignment, background box (`TextSection`, `EnhancedTextPreview`) | native | OpenCut Text section |
| Text stroke and shadow (`TextSection`) | [ ] port P2 | OpenCut text has no stroke or shadow; high-contrast captions over busy footage need them |
| Text in/out animations: fade, slide, typewriter, bounce, pop (`TextAnimationSection`) | [ ] port P2 | Fade/slide/pop as keyframe presets; typewriter needs per-character reveal |
| Karaoke / word-highlight captions: render's `animationStyle: "karaoke"` with word timings (`caption-animation-renderer`) | [ ] port P1 | Today captions are 3-word phrases with a pop-in (v2's own OpenCut path did the same). Word highlight is the caption look render asks for |
| Auto captions from audio (`AutoCaptionPanel`) | native | OpenCut Captions tab (in-browser Whisper) plus SRT/ASS import. ESTA's own captions come from timestamps via render |
| Audio-text sync: offset captions against audio (`AudioTextSyncPanel`, `audio-text-sync-bridge`) | [ ] port P3 | Kept at the user's request (2026-09-26) rather than dropped. Not used by the pipeline today: Captions come from faster-whisper word timings on the final audio, so they're already in sync. |
| Script view (`ScriptViewDialog`) | native | v3 Script panel |

## Audio

| v2 feature (source) | Status | v3 / plan |
|---|---|---|
| Waveforms, clip volume, volume keyframes and fades | native | OpenCut audio, volume line, keyframes |
| Audio mixer: channel strips, faders, pan, meters, mute/solo (`AudioMixer`, `ChannelStrip`) | [ ] port P2 | A mixer panel over the audio tracks |
| Audio effects: EQ, compressor, pan (`AudioEffectsSection`, `audio-bridge-effects`) | [ ] port P2 | |
| Audio effects: reverb, delay (`AudioEffectsSection`) | [ ] port P3 | |
| Auto ducking of music under voice (`AudioDuckingSection`) | [ ] port P2 | Volume keyframes on the music from the voice track's speech. `tools/audio/mix.py --bake` does this in the pipeline today |
| Noise reduction (`NoiseReductionSection`) | [ ] port P3 | For self-recorded VO |
| Auto cut silence (`AutoCutSilenceSection`, `silence-cut-bridge`) | [ ] port P3 | Kept at the user's request (2026-09-26) rather than dropped. Not used by the pipeline today: `tools/audio/tighten.py` cuts dead air in the pipeline before timestamps, so the timeline never gets it. |
| Music and sound library (`MusicLibraryPanel`) | native | OpenCut Sounds tab (Freesound) plus render's SFX from the plan. Search needs a real `FREESOUND_API_KEY` in `apps/editor/.env.local`; `scripts/dev.ts` writes a placeholder |
| Text to speech, ElevenLabs (`TextToSpeechPanel`, `VoiceBrowser`, `ModelSelector`, `AudioResult`, `tts-store`) | [ ] port P3 | Kept at the user's request (2026-09-26) rather than dropped. Not used by the pipeline today: The Voice stage produces the voiceover (IndexTTS2 / XTTS / self-record); a second paid TTS path in the editor would bypass it. |

## Project, export and app

| v2 feature (source) | Status | v3 / plan |
|---|---|---|
| Export: format, quality, with/without audio (`ExportDialog`) | native | OpenCut export, with v3's originals-only guard (M3) |
| Export presets: YouTube, Shorts, TikTok, Reels, Instagram, X, LinkedIn, 4K, ProRes (`export-presets`) | [ ] port P2 | Platform presets for resolution, fps and bitrate. ProRes isn't encodable in the browser, so those presets are dropped with it |
| Auto-save and crash recovery (`auto-save`, `RecoveryDialog`, `useProjectRecovery`, `media-recovery`) | native | OpenCut autosave to IndexedDB/OPFS; the project is rebuilt from render at any time |
| Session file sync and write-back to `<id>.openreel.json` (`session-file-sync`, `disk-sync`) | native | M3: the project follows render and conflicts ask. Edits live in the OpenCut project instead of being written back to the render file |
| Placeholder hydration and asset streaming (`hydrate-placeholders`, `stream-assets`) | native | M3 pending shots |
| Stages panel, writing stage, line editor (`stages/*`) | native | v3 stage rail and workspaces (M1), Script panel and line editor (M2) |
| Welcome screen, recent projects, new session, project switcher (`welcome/*`, `ProjectSwitcher`) | native | v3 session list and create/import (M1) |
| Background colour, blur, gradients (`background-generator`) | native | OpenCut project background |
| Stickers (`StickerPicker`, `StickerPickerPanel`) | native | OpenCut Stickers tab |
| Shapes (`ShapeSection`, `ShapeClipComponent`) | native | OpenCut graphics: rectangle, ellipse, polygon, star |
| SVG import (`SVGImporter`, `SVGSection`) | [ ] port P3 | Import an SVG as a graphic |
| Templates: save, browse, variables, gallery, cloud (`SaveTemplateDialog`, `TemplatesBrowserPanel`, `TemplateVariablesPanel`, `TemplateGallery`, `template-cloud-service`) | [ ] port P3 | Kept at the user's request (2026-09-26) rather than dropped. Not used by the pipeline today: Every ESTA timeline is built by render from the plan; editor-side templates would compete with that. Cloud templates are also a cloud service (non-goal). |
| Screen recorder (`ScreenRecorder`, `RecordingControls`, `RecordingCountdown`, `recorder-store`) | [ ] port P3 | Kept at the user's request (2026-09-26) rather than dropped. Not used by the pipeline today: No stage uses screen captures; the self-record VO path records in the audio skill. |
| AI tools hub (`AIGenTab`) | [ ] port P3 | Kept at the user's request (2026-09-26) rather than dropped. Not used by the pipeline today: A menu of the features above (TTS, captions, templates, music, multi-cam); each is decided in its own row. |
| Settings: API keys, master password, general (`settings/*`, `secure-storage`) | [ ] port P3 | Kept at the user's request (2026-09-26) rather than dropped. Not used by the pipeline today: Keys live in `config.yaml`, which the tools read; OpenCut keeps its own editor settings. |
| Guided tours (`tour/*`) | [ ] port P3 | Kept at the user's request (2026-09-26) rather than dropped. Not used by the pipeline today: Onboarding for OpenReel's UI, which v3 doesn't have. |
| Share page and share service (`SharePage`, `share-service`) | dropped | SPEC non-goal: cloud hosting |
| Chat panel as an in-app agent (`ChatPanel`, `bridges/*` as agent tools) | dropped | SPEC non-goal: replaced by the real Claude Code chat with the live-edit MCP tools (M1, M3) |
| Mobile blocker (`MobileBlocker`) | native | OpenCut's MobileGate; mobile is a SPEC non-goal |
| Analytics (`useAnalytics`) | dropped | SPEC non-goal: local single user |
| Toasts, error boundary, processing overlay | native | OpenCut equivalents |

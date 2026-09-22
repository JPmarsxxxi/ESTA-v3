# Profile

This folder holds Claude's running notes on the user's tone, common style choices, recurring topics, and things they don't like. It is read by every conversational skill before it opens, so Claude can adapt its phrasing and skip questions already answered.

## How it gets built

`profile/preferences.md` (which does not exist yet) will be created and updated by a future `profile-update` skill that distills patterns from `sessions/*/conversation.jsonl` after each session.

## Manual edits

You can drop notes here yourself if you want Claude to adopt them right away. Example contents for `profile/preferences.md`:

```
- Speaks casually, dislikes corporate phrasing.
- Default style is meme-heavy commentary.
- Calls football "football", not "soccer".
- Usually wants 2-3 minute videos for the main channel, 30-60s clips for shorts.
```

Keep it human-readable. Claude reads the file in full each time, so don't make it huge — synthesized observations, not full transcripts (the raw transcripts live in `sessions/*/conversation.jsonl`).

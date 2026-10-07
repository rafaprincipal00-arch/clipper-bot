# Clip editing playbook (read by the bot on every edit)

Distilled from clipper tutorials (DaVinci/CapCut clipper edits, Twitch-to-TikTok workflows, retention
editing, hook formulas). `highlights.py` pastes this file into the Gemini edit prompt; `render.py`
implements the visual/audio rules. Change the rules here, not in the prompt.

## 1. Pick the moment
- Only moments with a payoff: a reaction, fail, roast, drama, shocking line, funny exchange with a punchline.
  Someone explaining, reading chat or chatting without a payoff is not a clip.
- 20-40 s. Never over 60 s. Long enough that a stranger understands it, short enough that nothing drags.

## 2. The hook (first 1-2 s decide the swipe)
- Second 0 is the strongest line or reaction, even if it happens later. No intro, no "hey guys", no
  loading screens, no dead air.
- Pick one hook type for every clip:
  - **revelation**: lead with the result, the thing people came to see ("He just lost $300K live").
  - **contrarian**: say the opposite of what the viewer expects ("Nobody cares about your headshot").
  - **stakes**: state the cost or consequence first, explain after ("One word cost him the whole deal").
- On-screen hook text (max 6 words) frames the moment: what the viewer is about to see, a question,
  or the stakes. It must not repeat the first spoken line word for word.

## 3. Cuts (the dopamine part)
- Something changes on screen every ~3 s: a cut, a punch-in, a new caption colour.
- Jump-cut every pause, filler word ("uh", "like", "you know"), repeat and side-tangent. Cut the yapping:
  what belongs in a vlog does not belong in a short.
- Never cut mid-word or mid-sentence, and never cut the set-up the payoff depends on.
- Opening shot punches in (zoom-out from close) so frame 1 already moves.
- Alternate zoom levels on consecutive cuts so jump cuts read as intentional.

## 4. Captions
- Burned in, big, centre-lower third, 2-3 words at a time, the spoken word pops in colour. Most people
  watch muted.
- 2-5 emphasis words per clip (the punchline word, numbers, names, insults-turned-safe, "NO", "WHAT")
  get a bigger, red pop. Pick the words that carry the joke or the stakes.
- Keep text inside the safe area: the platform UI covers the bottom ~15% and the right edge.

## 5. Sound
- A light music bed under the voice, ducked whenever someone speaks. Voice always wins.
- Sound effects, low in the mix: a whoosh on each cut, a pop when the hook text lands, a bass hit on
  the payoff. They make cuts feel deliberate; too loud and they feel cheap.
- Only music we are licensed for (repo `assets/music`, credited) or TikTok's own library. Never add a
  second song on top of a clip that already has a bed.

## 6. Ending
- End on the payoff. Cut within ~0.3 s of the last word of the punchline or the end of the reaction.
  No outro, no fade to black, no "follow for more".
- If the moment allows it, end on a line that makes the start make sense again (loop): rewatches count.

## 7. Post caption
- Formula: emotion word + niche + outcome. "I can't believe he lost it all on one hand" beats
  "crazy clip lol". The platforms use the caption to decide who to show it to; it is search text.
- Under 90 characters, no hashtags in the title (the campaign hashtags are appended), brand-safe:
  no slurs or profanity, or campaigns reject it.

## 8. Every account, every day
- Consistency beats perfection: post the daily maximum on every account rather than polishing one clip.
- Each clip goes to one account only; never repost the same file across accounts.

# Viral clip playbook (read by the bot on every edit)

Sources: 12 clipper tutorials (CapCut/DaVinci clipper edits, Twitch-to-TikTok workflows, retention editing,
hook formulas), the most viewed streamer Shorts on YouTube (Oct 2026 sample, 10 searches, ≤75 s) and this
bot's own results. `highlights.py` pastes this file into the Gemini prompt together with the live
"what worked on our channels" notes from `data/performance.json`. `render.py` implements the visual and
audio rules; the TikTok poster adds the platform song. Change the rules here, not in the prompt.

## 1. What a viral moment is (pick or skip)
A moment is viral when a stranger who has never heard of the streamer gets it in 3 seconds and feels
something strong: shock, second-hand embarrassment, laughter, anger, awe. The most viewed streamer Shorts
all fall in a few families:

| Family | What happens | Real examples (views) |
|---|---|---|
| **Scare / physical reaction** | jump-scare, scream, falls off the chair, rage-quit | "iShowSpeed gets jumpscared" (23.8M) |
| **Caught / walk-in** | parent, girlfriend or police walks in; something seen on camera that should not be | "Mum walks in on 15 year old streamer" (6.3M) |
| **Epic fail / worst ever** | the worst round, the worst trade, losing big live | "xQc performs the worst round in CSGO history" (3.9M) |
| **Celebrity collision** | famous guest breaks character, gets pressed, awkward exchange | "Adin Ross makes Andrew Tate break character" (3.1M), "Pressed by MrBeast" |
| **Relatable "2 types of people"** | two reactions to the same thing, viewers pick a side | "2 types of people: negaoryx and xQc" (14.6M) |
| **Unhinged line / roast** | a sentence nobody should say on stream, a savage comeback | "I gotta scam old people" (our best: 2.3K) |
| **Live drama / IRL chaos** | crash, fight, stranger confrontation, getting kicked out | "DON'T LET JAMES DRIVE!" (our 3rd best) |
| **Real-world event live** | earthquake, power cut, something big happens on stream | "Streamer catches earthquake" (1.1M) |

**Skip** (score under 40 even if mildly funny): explaining, teaching, reading chat, thanking subs, talking
about charts/indicators, inside jokes that need a week of lore, moments where the payoff is only on a
screen we cannot read in 9:16. Our data agrees: pure trading talk ("the book trading indicator",
"should I buy this coin?") got 0-7 views; the same streamer's human moments got 500+.

Score honestly: 85+ only if it fits a family above AND the payoff is visible/audible in the clip.

## 2. The hook (first 1-2 s decide the swipe)
- Second 0 is the strongest line or reaction, even if it happens later. No intro, no "hey guys", no
  loading screens, no dead air. For scares/fails you may show the reaction first (0.5-1 s), then go back to
  the set-up: the viewer stays to see what caused it.
- Pick one hook type for every clip:
  - **revelation**: lead with the result ("He just lost $300K live").
  - **contrarian**: the opposite of what the viewer expects ("Nobody cares about your headshot").
  - **stakes**: the cost or consequence first ("One word cost him the whole deal").
- On-screen hook text (max 6 words) frames the moment: who + what is about to happen, a question, or the
  stakes. Name the streamer when he is famous ("Speed vs the scariest game"). It must not repeat the first
  spoken line word for word.

## 3. A good edit
- Fast, but readable: the viewer must always know who is talking and why it matters.
- One idea per clip. If two moments are good, they are two clips.
- Set-up as short as possible, payoff never trimmed. Keep the reaction after the payoff (1-2 s of the
  streamer's face/scream is the punchline for the viewer).
- Captions: burned in, big, centre-lower third, 2-3 words at a time, the spoken word pops in colour (most
  people watch muted). 2-5 emphasis words (the punchline word, numbers, names, "NO", "WHAT") get a bigger
  red pop. Text stays inside the safe area: the platform UI covers the bottom ~15% and the right edge.
- Facecam visible during reactions. If the game/screen matters, keep it on screen at the same time.

## 4. Cuts (the dopamine part)
- Something changes on screen every ~2-4 s: a cut, a punch-in, a new caption colour.
- Jump-cut every pause, filler word ("uh", "like", "you know"), repeat, side-tangent and chat-reading. What
  belongs in a vlog does not belong in a short.
- Never cut mid-word or mid-sentence, never cut the set-up the payoff depends on, never cut the reaction.
- Opening shot punches in (zoom-out from close) so frame 1 already moves; alternate zoom levels on
  consecutive cuts so jump cuts read as intentional.

## 5. When to end
- End on the payoff: within ~0.3 s of the last word of the punchline, or 1-2 s into the reaction when the
  reaction IS the payoff. No outro, no fade to black, no "follow for more", no trailing chatter.
- 20-40 s. Shorter is better when the moment is simple: a scare can be 15-20 s, a story needs 35-40 s.
  Never pad to reach a length.
- Loop when possible: end on a line or frame that makes the first second make sense again. Rewatches count
  as much as full views.

## 6. Music per platform
Paid/commercial trending songs are licensed **inside each app's library only**. Embedding them in the
file gets the clip claimed or muted and Content Rewards rejects it. So:
- **TikTok**: the clip is uploaded WITHOUT a background bed; the poster adds a trending song from
  TikTok's own library in the TikTok Studio editor, quiet under the voice, chosen by the clip's mood from
  `config/music.json`. Pick the mood carefully, it decides the song.
- **YouTube Shorts**: the API cannot attach YouTube's library songs, so Shorts keep the bot's own licensed
  bed (Kevin MacLeod, CC BY, credited in the description) ducked under the voice.
- **Instagram Reels** (when connected): same rule as TikTok, song from the Reels library.
- Never two songs at once. Voice always wins: in a conversation the song is barely audible.
- Moods: hype (wins, money, flexing), chaos (fights, crashes, rage), drama (beef, confrontation, sad),
  sus (caught, suspicious, awkward silence), funny (fails, roasts), awkward (cringe), chill (wholesome, story).

## 7. Sound effects
Low in the mix: a whoosh on each cut, a pop when the hook text lands, a bass hit on the payoff. They make
cuts feel deliberate; too loud and they feel cheap. Never over a scream or the punchline word.

## 8. Post caption
- Formula: emotion word + who + outcome. "Speed was NOT ready for this" beats "crazy clip lol". The platforms
  use the caption to decide who to show it to; it is search text. Name the streamer when he is famous.
- Under 90 characters, no hashtags in the title (the campaign hashtags are appended), brand-safe:
  no slurs or profanity, or campaigns reject it.

## 9. Every account, every day
- Consistency beats perfection: post the daily maximum on every account rather than polishing one clip.
- Each clip goes to one account only; never repost the same file across accounts.
- Feed the winners: creators that get views on our channels get their clips made first
  (`data/performance.json` reorders the sources every run).

# Clipper Bot

Automatic clipper that runs **in the cloud** (GitHub Actions, free). It doesn't download or edit anything on your PC.

Panel: https://clipper-bot.vercel.app · Logs / manual run: Actions tab → `clipper` → *Run workflow*.

## What it does every 6 hours
1. **Discovery**: reads every campaign on Content Rewards (Whop), drops non-English ones and UGC/slideshow/music campaigns, and ranks the 15 best by CPM × remaining budget × competition. Writes `data/campaigns.json` and adds each campaign's video sources (YouTube, Twitch, Kick) to `config/sources.json`.
2. **Clips**: for each enabled source with a new VOD, it downloads only the audio, finds the volume peaks, transcribes them with Whisper, and Gemini picks the best 20–55 s cut with a hook. It then downloads only that piece of video and renders it at 1080×1920 with karaoke captions and the hook.
3. **Publishing**: YouTube Shorts, TikTok and Instagram Reels, whichever are connected. If one fails, the others still go out.
4. Saves `data/clips.json` (feeds the panel) and attaches the mp4s to the `clips` release.

## What you have to do by hand (no API exists for it)
- **Join the campaigns** on contentrewards.com and paste each published post's link into *Submit*. Campaigns marked "requiere solicitud" (application required) also need approval.
- Read each campaign's rules: required caption text, a link in your bio, minimum length. Put them in `config/sources.json` (`hashtags`, `credit`) and set `enabled: true`.

## Secrets (Settings → Secrets → Actions)
| Secret | What it's for |
|---|---|
| `GEMINI_API_KEY` | choosing cuts (already set) |
| `YTDLP_COOKIES` | cookies.txt from a throwaway YouTube account: YouTube blocks GitHub's servers without it |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | upload Shorts |
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN` | upload to TikTok |
| `IG_ACCESS_TOKEN`, `IG_USER_ID` | publish Reels |

You get the tokens on https://clipper-bot.vercel.app/connect.html (needs `*_CLIENT_ID/SECRET` and `IG_APP_ID/SECRET` in Vercel's environment variables).

## Platform limits
- TikTok, app not audited: posts stay **private** (SELF_ONLY) and the account has to be private. Going public requires TikTok's audit.
- YouTube, project not verified: uploads stay **private** until the project passes the API audit. About 6 uploads a day with the free quota.
- Instagram: needs a Creator/Business account. 50 posts a day; the token lasts 60 days.

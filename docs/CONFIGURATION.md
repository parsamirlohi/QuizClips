# Configuration

Everything is set with environment variables in a `.env` file next to `app.py` (copy `.env.example`). `python3 tools/set_key.py` creates it for you.

## Options (all go in `.env`)
- `ANTHROPIC_API_KEY=` Claude writes the questions and picks footage searches that fit the topic without
  giving away the answer. Without it, questions come from the free Open Trivia DB.
- `GEMINI_API_KEY=` Gemini writes the footage searches so each clip matches its question (free key at
  aistudio.google.com/apikey; run `python tools/set_key.py` and choose 3). `FOOTAGE_LLM=gemini|claude|none` picks the
  provider; `GEMINI_MODEL=` overrides the model.
- `blocked_clips.json` (optional): a list of Pixabay clip ids to never use, e.g. `[12345, 67890]`. The id is the
  number in the clip's filename in `cache` (`pixabay_12345.mp4`).
- `THINK_SECONDS=7` length of the trivia countdown before each reveal. `THINK_PERSONALITY_SECONDS=10` is the time to pick an answer in personality quizzes.
- `VIDEO_ENCODER=h264_videotoolbox` faster rendering on a Mac (`h264_nvenc` on an NVIDIA GPU).
- `PEXELS_API_KEY=` use Pexels instead (sharper portrait video). If both keys are set, Pexels is used; force
  one with `VIDEO_SOURCE=pixabay`.
- Your own bing sound: put `bing.wav` (or .mp3) in the `assets` folder.
- Test mode: `MOCK=1` runs offline with placeholder questions, backgrounds and voice.

## Looks
The page has a **Look** section with 24 styles (background + matching header/answer-bar colours); pick one, or
"Surprise me" for a random one each video. Your choice is remembered in the browser.
- Backgrounds are made once, the first time a look is used (a few seconds), into `assets/backgrounds/`. Run
  `python3 tools/make_backgrounds.py` to make them all now. Delete that folder to regenerate.
- The two "Blurred Clip" looks use each question's own footage, blurred, as the background.
- `looks.py` lists every look; `styles.py` / `backgrounds.py` draw them. After adding or changing one, run
  `python3 tools/make_look_thumbs.py` to refresh the pictures in the selector, then
  `python3 tools/make_look_loops.py --all` to refresh the animated previews (the phone and the hover loops).

## Notes
- Pixabay allows 100 requests per minute. Each video uses about one request per question, and results are cached.
- Pixabay has no portrait filter, so its widescreen clips are center-cropped to vertical.
- Pixabay asks that you credit them when showing search results; the page footer does this.
- Downloaded clips are cached in `cache` so repeats don't re-download.
- Only your newest 10 finished videos are kept in `output`; older ones are deleted after each new video. Change it with `MAX_KEEP_VIDEOS=` in `.env` (0 keeps everything). Download the ones you want to keep.
- Keep your `.env` private. Don't share it or zip it.

## Troubleshooting
- **Banner says no key / no settings file:** it shows exactly where it looks. The file must be named `.env`
  (not `.env.example`) and sit next to `app.py`. Run `python tools/set_key.py` to create it correctly.
  After changing it, stop the app (Ctrl+C) and start it again.
- **"Pixabay error 400/401":** the key was pasted wrong. Run `python tools/set_key.py` again.
- **"Could not fetch questions":** the free question site allows one request every few seconds. Wait a bit and retry.
- **Narration fails:** the voices come from Microsoft's free service and need an internet connection.

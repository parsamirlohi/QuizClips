# Quizclips

Click **Generate** and get a new vertical (1080x1920) trivia quiz video for TikTok:

- Fresh questions every time (it remembers past ones and avoids repeats)
- The correct answer lands on a different letter each time (A-D, never the same twice in a row)
- A Pixabay stock video behind each question, searched from the question's topic
- AI narration reads the question and each choice, then announces the answer
- A "bing" sound on the reveal, with a countdown tick before it

## Quick start

1. Install Python 3.10 or newer from python.org (Windows: tick "Add Python to PATH").
2. Get your free Pixabay key: sign up at pixabay.com, then open https://pixabay.com/api/docs/ while logged in. The key is shown next to `key (required)`.
3. Start the app:
   - **Mac:** double-click `run_mac.command` (if macOS blocks it, right-click, Open; or run `chmod +x run_mac.command` first).
   - **Windows:** double-click `run_windows.bat`.
4. The first time, it installs what it needs, asks you to paste your key, and saves it to a `.env` file for you.
5. Your browser opens http://localhost:8000. Pick the number of questions and a voice, then click **Generate quiz video**.

Next time, just double-click the same launcher. Videos are saved in the `output` folder.
A 5-question video is about 1.5 minutes long and takes a minute or two to render.

Prefer the terminal? `pip install -r requirements.txt`, then `python tools/set_key.py`, then `python app.py`
(use `python3` / `pip3` on a Mac).

## Troubleshooting

- **Banner says no key / no settings file:** it shows exactly where it looks. The file must be named `.env`
  (not `.env.example`) and sit next to `app.py`. Run `python tools/set_key.py` to create it correctly.
  After changing it, stop the app (Ctrl+C) and start it again.
- **"Pixabay error 400/401":** the key was pasted wrong. Run `python tools/set_key.py` again.
- **"Could not fetch questions":** the free question site allows one request every few seconds. Wait a bit and retry.
- **Narration fails:** the voices come from Microsoft's free service and need an internet connection.

## Video types

Pick a type at the top of the Create page. Everything except Trivia needs a free `GEMINI_API_KEY` in `.env`, because Gemini writes the script from your topic.

- **Trivia quiz**: multiple-choice questions with a reveal (Open Trivia DB).
- **Personality quiz**: "Which season are you?" Questions whose choices each lead to one of four results, shown as "Mostly A, B, C, D" at the end.
- **Would you rather**: two options, a countdown, then what each pick says about you.
- **Story**: you are the hero. "Choose your path" shows where both options lead; "Would you survive?" hides a few deadly traps among the decisions.
- **Rankings**: a countdown from the last place to number one, one clip per item.
- **Fun facts**: short surprising facts, one clip per fact.
- **Odd one out**: four things, three belong together, viewers spot the one that doesn't.
- **Guess the clip**: stock footage starts as big blocks and gets sharper while viewers pick what it shows.
- **What's missing**: a grid of pictures to memorize, then one disappears. The pictures are Twemoji (CC-BY 4.0, see `assets/emoji/LICENSE.txt`) and need no AI.

Leave the topic blank for a surprise. `content.py` writes the scripts and `formats.py` builds the videos.

Colors can be changed for every video type. The phone preview in Studio is redrawn by `previews.py` (through `/api/preview`) as the colors change; `preview_data.py` holds the examples it shows for each look.

## Looks

The page has a **Look** section with 24 styles (background + matching header/answer-bar colours); pick one, or
"Surprise me" for a random one each video. Your choice is remembered in the browser.
- Backgrounds are made once, the first time a look is used (a few seconds), into `assets/backgrounds/`. Run
  `python3 tools/make_backgrounds.py` to make them all now. Delete that folder to regenerate.
- The two "Blurred Clip" looks use each question's own footage, blurred, as the background.
- `looks.py` lists every look; `styles.py` / `backgrounds.py` draw them. After adding or changing one, run
  `python3 tools/make_look_thumbs.py` to refresh the pictures in the selector, then
  `python3 tools/make_look_loops.py --all` to refresh the animated previews (the phone and the hover loops).

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

## Notes

- Pixabay allows 100 requests per minute. Each video uses about one request per question, and results are cached.
- Pixabay has no portrait filter, so its widescreen clips are center-cropped to vertical.
- Pixabay asks that you credit them when showing search results; the page footer does this.
- Downloaded clips are cached in `cache` so repeats don't re-download.
- Only your newest 10 finished videos are kept in `output`; older ones are deleted after each new video. Change it with `MAX_KEEP_VIDEOS=` in `.env` (0 keeps everything). Download the ones you want to keep.
- Keep your `.env` private. Don't share it or zip it.

## Files

| File | What it does |
| --- | --- |
| `run_mac.command`, `run_windows.bat` | One-click launchers (install, set key on first run, start) |
| `tools/set_key.py` | Asks for your key and saves the `.env` file |
| `app.py` | Web server and the Generate button |
| `pipeline.py` | Builds one video start to finish and sets the timing |
| `questions.py` | Gets questions, shuffles answer letters, builds video search words |
| `videos.py` | Searches and downloads background videos (Pixabay and Pexels) |
| `tts.py` | AI narration |
| `audio.py` | Mixing and the bing / tick / pop sounds |
| `render.py` | Draws the quiz graphics and renders each scene with ffmpeg |

### Folders

| Folder | What's in it |
| --- | --- |
| `static/` | The website and Studio pages, styles, fonts and the look previews: pictures in `looks/`, animated loops in `looks/loops/`, the sharp question graphics in `looks/overlay/` |
| `assets/` | Fonts, backgrounds, logo and sounds the videos use |
| `tools/` | Optional one-off scripts (set your key, make previews, check footage, export the waitlist). Run them from the project folder, e.g. `python3 tools/export_waitlist.py` |
| `design/` | Unused logo and favicon options, kept for reference |
| `output/`, `cache/`, `work/` | Made videos, downloaded clips, temporary files (not in git) |

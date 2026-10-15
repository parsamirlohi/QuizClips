# Quiz Video Maker

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
5. Your browser opens http://localhost:8000. Pick the number of questions and a voice. Click **Preview voice** to hear a short sample, then click **Generate quiz video**. Voice previews also work before you add a stock-video API key.

Next time, just double-click the same launcher. Videos are saved in the `output` folder.
A 5-question video is about 1.5 minutes long and takes a minute or two to render.

Prefer the terminal? `pip install -r requirements.txt`, then `python set_key.py`, then `python app.py`
(use `python3` / `pip3` on a Mac).

## Setup guide for Parsa: Ollama, Gemma and Pixabay

These steps use local Gemma for questions and footage checks, and Pixabay for stock clips.

### 1. Install Python and Ollama

Install [Python 3.10 or newer](https://www.python.org/downloads/) and
[Ollama](https://ollama.com/download). On Windows, tick **Add Python to PATH** during
installation. Keep Ollama running, then open a new PowerShell or Terminal window.

### 2. Download and test Gemma

Run these commands to download [Gemma 4](https://ollama.com/library/gemma4) and check
that it responds:

```sh
ollama pull gemma4:latest
ollama run gemma4:latest "Say hello"
```

Wait for the download to finish. The app uses this model to generate questions and
check sampled frames from candidate videos.

### 3. Get your Pixabay API key

Create a Pixabay account, sign in, and open the
[Pixabay API documentation](https://pixabay.com/api/docs/). Copy the key shown next to
**key (required)**. Keep the key private.

### 4. Create your settings file

Open the project folder containing `app.py`. Create a plain-text file named `.env`
in that folder with the following contents, replacing `paste_your_key_here` with your
Pixabay key. If `.env` already exists, update these lines in it:

```dotenv
PIXABAY_API_KEY=paste_your_key_here
VIDEO_SOURCE=pixabay
QUESTION_SOURCE=ollama
OLLAMA_MODEL=gemma4:latest
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_TIMEOUT=180
VIDEO_REVIEW=1
THINK_SECONDS=5
```

On Windows, choose **All files** when saving from Notepad so the filename stays `.env`.
You do not need an Anthropic API key for this setup.

### 5. Start the app

On **Windows**, double-click `run_windows.bat` in the project folder.

On **Mac**, double-click `run_mac.command`. If it will not open, run these commands
from Terminal in the project folder:

```sh
chmod +x run_mac.command
./run_mac.command
```

The launcher installs the Python dependencies and starts the app. Keep its terminal
window open. Your browser should open [http://localhost:8000](http://localhost:8000);
open that address yourself if it does not.

### 6. Make your first video

Start with **3 questions**, choose a category and voice, then click **Generate quiz video**.
Wait for the progress bar to finish. You can preview and download the result in the
browser; the MP4 is also saved in the `output` folder. Gemma's footage checks add time.

For later runs, keep Ollama running and launch the app the same way. After changing
`.env`, stop the app with **Ctrl+C** in its terminal window and launch it again.
Stock footage and narration need an internet connection.

## Troubleshooting

- **Banner says no key / no settings file:** it shows exactly where it looks. The file must be named `.env`
  (not `.env.example`) and sit next to `app.py`. Run `python set_key.py` to create it correctly.
  After changing it, stop the app (Ctrl+C) and start it again.
- **"Pixabay error 400/401":** the key was pasted wrong. Run `python set_key.py` again.
- **"Could not fetch questions":** the free question site allows one request every few seconds. Wait a bit and retry.
- **Narration fails:** the voices come from Microsoft's free service and need an internet connection.

## Options (all go in `.env`)

- `ANTHROPIC_API_KEY=` Claude writes the questions and picks footage searches that fit the topic without
  giving away the answer. Without it, questions come from the free Open Trivia DB.
- `THINK_SECONDS=5` length of the countdown before each reveal.
- `VIDEO_ENCODER=h264_videotoolbox` faster rendering on a Mac (`h264_nvenc` on an NVIDIA GPU).
- `PEXELS_API_KEY=` use Pexels instead (sharper portrait video). If both keys are set, Pexels is used; force
  one with `VIDEO_SOURCE=pixabay`.
- Your own bing sound: put `bing.wav` (or .mp3) in the `assets` folder.
- Test mode: `MOCK=1` runs offline with placeholder questions, backgrounds and voice.

## Notes

### Local Gemma questions and footage checks

Run [Ollama](https://ollama.com/) with a vision-capable Gemma model installed
(`ollama pull gemma4` if it is not already installed). Add these lines to your `.env`
and restart the app:

```dotenv
QUESTION_SOURCE=ollama
OLLAMA_MODEL=gemma4:latest
VIDEO_REVIEW=1
```

Gemma generates questions, four answer choices, and topic-based footage search phrases.
The app validates the response, removes duplicate questions within the batch, and uses
the existing history to prefer unused questions. If Ollama is unavailable or returns too
few usable questions, question generation falls back to Open Trivia DB. Generated trivia
answers are not independently fact-checked.

With `VIDEO_REVIEW=1`, each candidate question clip is checked using frames from 10%,
50%, and 90% of its duration, cropped to the same window shown in the final quiz.
Gemma first describes the frames without seeing the question, then checks that description
against the question to reduce guesses based on the requested subject.
Gemma must accept the visible subject as relevant to the actual question; rejected clips
are skipped. This checks contextual subjects (for example, river footage for a river
question), not the exact identity or location of a landmark. Up to three candidates
are checked per search phrase. When all searches fail, Gemma uses the failed queries and
rejection reasons to propose up to three new phrases and searches the same provider again.
Rejected clips and previous phrases are skipped across retries. This works with Pixabay
and Pexels when using local questions or footage review. VIDEO_SEARCH_ROUNDS=3
allows the initial search plus two revised rounds (1 disables retries; maximum 5).
If all rounds fail, or the API/review service fails, generation reports an error rather
than using unchecked footage. Footage details identify successful revised search rounds.
The result's footage details include Gemma's acceptance reason. Intro and outro scenes
are decorative and do not need topic checks. Frame sampling can miss other parts of a clip
and adds generation time.

Set `VIDEO_REVIEW=0` to skip vision checks, or enable `VIDEO_REVIEW=1` with Open Trivia DB
questions to use Gemma only for footage review. `OLLAMA_BASE_URL` defaults to
`http://127.0.0.1:11434`; `OLLAMA_TIMEOUT` defaults to 180 seconds per model request.
Stock footage and the current narration service still need internet access and their
usual settings. `MOCK=1` continues to run offline and skips Ollama.

Run the local integration tests with `python -m unittest discover -s tests -v`.

## Storage and footage

- Pixabay allows 100 requests per minute. Each video uses about one request per question, and results are cached.
- Pixabay has no portrait filter, so its widescreen clips are center-cropped to vertical.
- Pixabay asks that you credit them when showing search results; the page footer does this.
- Footage is stored in each job's own temporary directory, so another job's cleanup cannot remove it during review or rendering. Set `KEEP_CACHE=1` to retain reusable downloads in `cache`; otherwise each job removes its own footage when it finishes or fails.
- Keep your `.env` private. Don't share it or zip it.

## Files

| File | What it does |
| --- | --- |
| `run_mac.command`, `run_windows.bat` | One-click launchers (install, set key on first run, start) |
| `set_key.py` | Asks for your key and saves the `.env` file |
| `app.py` | Web server and the Generate button |
| `pipeline.py` | Builds one video start to finish and sets the timing |
| `questions.py` | Gets questions, shuffles answer letters, builds video search words |
| `local_model.py` | Structured question and vision requests to local Ollama |
| `footage_review.py` | Samples and checks stock-video frames with Gemma |
| `videos.py` | Searches and downloads background videos (Pixabay and Pexels) |
| `tts.py` | AI narration |
| `audio.py` | Mixing and the bing / tick / pop sounds |
| `render.py` | Draws the quiz graphics and renders each scene with ffmpeg |

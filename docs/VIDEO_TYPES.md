# Video types
Pick a type at the top of the Create page. Everything except Trivia needs a free `GEMINI_API_KEY` in `.env`, because Gemini writes the script from your topic.

- **Trivia quiz**: multiple-choice questions with a reveal (Open Trivia DB).
- **Personality quiz**: "Which season are you?" Questions whose choices each lead to one of four results, shown as "Mostly A, B, C, D" at the end.
- **Would you rather**: two options, a countdown, then what each pick says about you.
- **Quest**: you are the hero. "Choose your path" shows where both options lead; "Would you survive?" hides a few deadly traps among the decisions.
- **Rankings**: a countdown from the last place to number one, one clip per item.
- **Fun facts**: short surprising facts, one clip per fact.
- **Odd one out**: four things, three belong together, viewers spot the one that doesn't.
- **Guess the clip**: stock footage starts as big blocks and gets sharper while viewers pick what it shows.
- **What's missing**: a grid of pictures to memorize, then one disappears. The pictures are Twemoji (CC-BY 4.0, see `assets/emoji/LICENSE.txt`) and need no AI.

Leave the topic blank for a surprise. `content.py` writes the scripts and `formats.py` builds the videos.

Every type also has an **I'll write it** editor, so you can type your own content (What's missing lets you pick the pictures).

Colors can be changed for every video type. The phone preview in Studio is redrawn by `previews.py` (through `/api/preview`) as the colors change; `preview_data.py` holds the examples it shows for each look.

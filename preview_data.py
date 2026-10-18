"""The question shown in each look's preview picture on the website, and the stock-video search that goes with it.
Used by make_look_thumbs.py. Keys are look names (see looks.py). Keep each question short enough for three lines."""

PREVIEWS = {
    "bubblegum":     {"q": "Which animal is known as the king of the jungle?", "a": ["Tiger", "Lion", "Leopard", "Cheetah"], "search": ["lion"]},
    "soft_cream":    {"q": "Which planet is called the Red Planet?", "a": ["Venus", "Mars", "Jupiter", "Saturn"], "search": ["mars red planet", "planet space"]},
    "slate":         {"q": "What is the capital of Japan?", "a": ["Seoul", "Tokyo", "Beijing", "Osaka"], "search": ["tokyo city", "japan city night"]},
    "midnight_gold": {"q": "How many strings does a standard guitar have?", "a": ["4", "5", "6", "8"], "search": ["guitar playing", "guitar strings"]},
    "obsidian_pink": {"q": "Which is the largest ocean on Earth?", "a": ["Atlantic", "Indian", "Pacific", "Arctic"], "search": ["ocean waves", "sea aerial"]},
    "flat_hills":    {"q": "Which of these birds cannot fly?", "a": ["Eagle", "Penguin", "Owl", "Falcon"], "search": ["penguin", "penguins ice"]},
    "night_skyline": {"q": "Which city is nicknamed the Big Apple?", "a": ["Chicago", "Boston", "New York", "Miami"], "search": ["new york city", "manhattan skyline"]},
    "blurred_dark":  {"q": "What is the hardest natural material?", "a": ["Gold", "Iron", "Diamond", "Quartz"], "search": ["diamond", "diamond jewelry"]},
    "blurred_tint":  {"q": "Which fruit is the base of guacamole?", "a": ["Mango", "Avocado", "Lime", "Banana"], "search": ["avocado", "guacamole"]},
    "ocean":         {"q": "What do honey bees make?", "a": ["Silk", "Honey", "Jam", "Syrup"], "search": ["honey bee", "bees honeycomb"]},
    "sunset":        {"q": "Which sport uses a shuttlecock?", "a": ["Tennis", "Badminton", "Squash", "Golf"], "search": ["badminton", "shuttlecock"]},
    "neon_night":    {"q": "Who painted the Mona Lisa?", "a": ["Van Gogh", "Picasso", "Da Vinci", "Monet"], "search": ["painting art museum", "paris louvre"]},
    "mint":          {"q": "How many continents are there?", "a": ["5", "6", "7", "8"], "search": ["earth globe space", "world map"]},
    "gold_black":    {"q": "Which planet is famous for its rings?", "a": ["Mars", "Venus", "Saturn", "Earth"], "search": ["saturn planet", "planet space"]},
    "sunburst":      {"q": "What is the tallest mountain above sea level?", "a": ["K2", "Everest", "Kilimanjaro", "Denali"], "search": ["mount everest", "mountain peak snow"]},
    "aurora":        {"q": "What are the northern lights also called?", "a": ["Zodiac", "Aurora Borealis", "Solar flare", "Meteor storm"], "search": ["aurora borealis", "northern lights"]},
    "candy_stripes": {"q": "Which country is famous for inventing pizza?", "a": ["France", "Italy", "Spain", "Greece"], "search": ["pizza", "italian pizza oven"]},
    "halftone":      {"q": "What is a baby kangaroo called?", "a": ["Cub", "Joey", "Pup", "Kit"], "search": ["kangaroo", "kangaroo australia"]},
    "confetti":      {"q": "Which instrument has black and white keys?", "a": ["Violin", "Drums", "Piano", "Flute"], "search": ["piano keys", "playing piano"]},
    "synthwave":     {"q": "Which planet is closest to the Sun?", "a": ["Mercury", "Venus", "Earth", "Mars"], "search": ["sun", "sun solar"]},
    "starfield":     {"q": "What is the name of our galaxy?", "a": ["Andromeda", "Milky Way", "Orion", "Sombrero"], "search": ["milky way night sky", "stars night sky"]},
    "bokeh":         {"q": "Which drink is made from roasted beans?", "a": ["Tea", "Coffee", "Juice", "Milk"], "search": ["coffee beans", "coffee pour"]},
    "paper_waves":   {"q": "What is the largest land animal?", "a": ["Rhino", "Elephant", "Giraffe", "Hippo"], "search": ["elephant", "elephants savanna"]},
    "hex_grid":      {"q": "Which language is spoken in Brazil?", "a": ["Spanish", "Portuguese", "French", "English"], "search": ["rio de janeiro", "brazil"]},
}

"""The curiosities of Bramblewick.

Little wonders scattered around the town and the island. Kimi knows what
each one is (they're listed in its system prompt) and can choose to
``examine`` them; every visit uncovers the next detail. They also appear in
the 3D world and on the map.

Placement hints (resolved to free spots in ``curio3d.curiosity_spots``):

* ``("near", angle, dist)``   - around a place: angle in degrees relative to
  the building's front (0 = towards the square), dist from its centre.
* ``("attach", angle, dist)`` - like near, but part of the building itself
  (no free-space check).
* ``("pond", angle, r)``      - on the lily pond.
* ``("shore", angle)``        - on the island's shore, world angle in degrees.
* ``("hill", angle, r)``      - on the wooded hills, world angle and radius.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Curiosity:
    id: str
    name: str
    zone: str | None          # place Kimi walks to first (None = nearest place)
    kind: str                 # 3D model
    spot: tuple
    size: float
    tags: tuple[str, ...]
    what: str                 # what it is - Kimi knows this
    details: tuple[str, ...]  # uncovered one per visit
    tall: bool = False


def C(id, name, zone, kind, spot, size, tags, what, details, tall=False) -> Curiosity:  # noqa: N802
    return Curiosity(id, name, zone, kind, spot, size, tuple(tags), what, tuple(details), tall)


CURIOSITIES: tuple[Curiosity, ...] = (
    # --- The Nest ---------------------------------------------------------------
    C("tiny_door", "The Tiny Green Door", "nest", "tiny_door", ("attach", 150, 62), 10, ["mystery", "doors", "oak"],
      "a thumb-sized green door carved into the old oak's roots, with a brass knob someone keeps polished",
      ["The knob is warm, as if someone just let go of it.",
       "There's a keyhole the size of a seed, and a faint smell of cinnamon from inside.",
       "A tiny welcome mat woven from grass has appeared. Someone small lives here, or wants Kimi to think so."]),
    C("acorn_chimes", "The Acorn Chimes", "nest", "acorn_chimes", ("near", -70, 175), 14, ["music", "acorns", "wind"],
      "acorns strung on threads from a crooked twig that clack in the wind like a tiny wooden xylophone",
      ["Each acorn makes a slightly different note.",
       "Kimi counts eleven acorns and one empty thread. Someone took an acorn, or it fell.",
       "On windy evenings the chimes play the same three notes over and over, almost like a tune."]),
    C("moss_armchair", "The Moss Armchair", "nest", "stump_chair", ("near", -125, 205), 22, ["moss", "wood", "comfort"],
      "an old tree stump so thickly covered in moss that it has grown into the exact shape of an armchair",
      ["It's the softest seat in Bramblewick.",
       "Under the moss are tree rings, far too many to count.",
       "Sitting in it, the whole Nest is framed between two branches like a picture."]),
    C("weather_jar", "The Weather Jar", "nest", "jar", ("near", 70, 185), 12, ["weather", "glass", "mystery"],
      "a glass jar on a flat stone that fogs, drips or sparkles a little before the weather changes",
      ["Today the glass is clear, with one tiny drop running down.",
       "A faded label says: 'Do not open. Weather inside.'",
       "The jar is always one step ahead of the sky. It's a better forecaster than the pigeons."]),
    C("lost_mitten", "The Lost Mitten", "nest", "mitten_twig", ("near", 165, 215), 10, ["mystery", "knitting", "lost things"],
      "a single red knitted mitten hung on a twig, waiting patiently for its owner",
      ["It's far too big for any bird.",
       "Something has been sleeping in it: there's a little nest of thistledown inside.",
       "A tag sewn inside says 'Wren's'. Kimi is a wren, and has never owned a mitten. Curious."]),
    C("root_maze", "The Root Maze", "nest", "root_loops", ("near", -160, 195), 26, ["insects", "puzzles", "roots"],
      "a tangle of roots that loops into a little maze, which the beetles use as a racetrack",
      ["Kimi traces the maze with a toe and gets lost twice.",
       "The beetles always race clockwise, never the other way.",
       "At the very centre lies a smooth white pebble, like a prize."]),

    # --- The Shrub ----------------------------------------------------------------
    C("green_hollow", "The Green Hollow", "shrub", "hollow_arch", ("attach", 150, 98), 18, ["secret places", "moss", "shrub"],
      "a secret tunnel into the heart of the Shrub, where the light turns green and the air smells of rain",
      ["Inside, sound goes soft, like being wrapped in a leaf.",
       "Someone has hung a tiny lantern made from a snail shell near the entrance.",
       "At the very back is a little room carpeted with moss. What lives deep inside the Shrub is quiet itself."]),
    C("giant_shell", "The Giant Snail Shell", "shrub", "big_shell", ("near", 85, 195), 18, ["snails", "spirals", "mystery"],
      "a snail shell as big as a teapot, spiralling up like a staircase; nobody knows whose it was",
      ["The spiral turns to the left, which is rare for snails.",
       "Hold an ear to it and you hear something like the sea, though the lake is calm.",
       "Scratched inside the rim: a tiny drawing of a snail wearing a crown."]),
    C("spider_harp", "The Spider Harp", "shrub", "web_frame", ("near", -80, 190), 16, ["spiders", "music", "dew"],
      "a huge cobweb strung between two twigs that hums softly whenever the wind blows through it",
      ["The spider who made it is very small and very proud.",
       "In the morning the dew turns it into a necklace of tiny lights.",
       "Each thread plays a different note, and the spider re-tunes it every evening."]),
    C("beetle_highway", "The Beetle Highway", "shrub", "pebble_line", ("near", 130, 215), 26, ["insects", "roads", "mystery"],
      "a lane of tiny pebbles and twigs that beetles march along every evening, always in the same direction",
      ["It's lined with even tinier pebbles, like a road with kerbs.",
       "The beetles carry crumbs one way and nothing back.",
       "The highway leads to a crack in a stone where something hums."]),
    C("berry_scale", "The Berry Scale", "shrub", "scale", ("near", -140, 205), 14, ["berries", "trade", "brass"],
      "an old brass balance where the Shrub's creatures trade berries, one for one, fair and square",
      ["One pan is dented, as if someone very heavy once sat in it.",
       "A blackberry balances exactly against three clover seeds.",
       "Engraved on the base: 'Honest weight, happy hearts.'"]),
    C("mushroom_ring", "The Mushroom Ring", "shrub", "mushroom_ring", ("near", 55, 250), 30, ["mushrooms", "fungi", "rain"],
      "a perfect ring of little white mushrooms that pops up after rain",
      ["There are exactly thirteen mushrooms.",
       "The grass inside the ring is greener than the grass outside.",
       "Kimi hops into the middle and, for a moment, everything goes very quiet."]),
    C("moth_lantern", "The Moth Lantern", "shrub", "jar_lantern", ("near", -40, 235), 10, ["moths", "light", "night"],
      "a jam-jar lantern hanging from a stick; at dusk the moths come to visit it",
      ["The candle inside never seems to burn down.",
       "The moths land on it in patterns, as if they're spelling something.",
       "Kimi spots a moth with wings like an old map."]),

    # --- The Shrine ----------------------------------------------------------------
    C("wishing_well", "The Wishing Well", "shrine", "well", ("near", -70, 195), 24, ["wells", "wishes", "echoes"],
      "an old stone well with a little roof; drop in a pebble and listen for the echo that sometimes answers back",
      ["The echo takes three seconds to come back. Kimi counted.",
       "Someone has carved little stars all around the rim.",
       "Once, the echo said Kimi's name before Kimi had said anything at all."]),
    C("seven_stones", "The Seven Stones", "shrine", "stone_circle", ("near", 125, 230), 40, ["stones", "history", "mystery"],
      "a ring of seven standing stones, each a different height, older than anyone remembers",
      ["The shortest stone is warm even in the shade.",
       "At noon their shadows all point to the middle, like the hands of a clock.",
       "Each stone has a faint carving: a leaf, a feather, a moon, a fish, a key, a cup and a wren."], tall=True),
    C("ribbon_tree", "The Ribbon Tree", "shrine", "ribbon_tree", ("near", -130, 205), 20, ["ribbons", "luck", "visitors"],
      "a small tree hung with ribbons that visitors tie on for good luck",
      ["There are ribbons of every colour except purple.",
       "The oldest ribbon has faded to the colour of milk.",
       "One ribbon is tied in a perfect bow with a wren's feather knotted into it."], tall=True),
    C("quiet_bell", "The Quiet Bell", "shrine", "bell_frame", ("near", 160, 175), 14, ["bells", "music", "listening"],
      "a bell with no clapper in a wooden frame; people say it rings only for those who listen very hard",
      ["Kimi listens and hears the wind, mostly.",
       "When it rains, the drops tap the bell and it hums.",
       "Late one night Kimi is sure it heard it ring, very softly."]),
    C("footprint_stone", "The Footprint Stone", "shrine", "flat_stone", ("near", 60, 235), 18, ["mystery", "giants", "stones"],
      "a flat stone with a huge footprint pressed into it, far too big for anyone in town",
      ["The footprint has four toes.",
       "Rainwater collects in it, making a tiny pond that frogs visit.",
       "Beside it, half hidden by moss, is a second, much smaller footprint."]),
    C("swap_box", "The Swap Box", "shrine", "swap_box", ("near", -40, 175), 10, ["trinkets", "visitors", "gifts"],
      "a little wooden box on a post where visitors leave a trinket and take another",
      ["Today it holds a button, a marble and a tiny spoon.",
       "The rule is painted on the lid: 'Take one, leave one, smile once.'",
       "Someone left a drawing of Kimi in it. It's a good likeness."]),
    C("moss_sundial", "The Moss Sundial", "shrine", "sundial", ("near", 100, 180), 14, ["time", "moss", "sun"],
      "a mossy stone sundial that is always exactly seven minutes fast",
      ["The hours are little pictures instead of numbers.",
       "The seven minutes never change, summer or winter.",
       "Engraved on its side: 'Early is on time.'"]),

    # --- Town Square ----------------------------------------------------------------
    C("stopped_clock", "The Stopped Clock", "square", "clock_post", ("near", 20, 168), 12, ["time", "clocks", "mystery"],
      "a clock on a tall post, stuck at seventeen minutes past four; nobody remembers why",
      ["Kimi checks every day: still 4:17.",
       "Inside the glass, a spider has made her home.",
       "The town's oldest pigeon says something wonderful happened at 4:17, but won't say what."], tall=True),
    C("bramble_statue", "The Statue of Bramble the Badger", "square", "statue", ("near", 200, 178), 18, ["history", "statues", "badgers"],
      "a statue of Bramblewick's founder, a badger holding a lantern in one paw and a book in the other",
      ["The plaque reads: 'He lit the way and wrote it down.'",
       "The stone book shows a map with an X on the Shrub.",
       "Someone puts a fresh flower in the lantern every morning."], tall=True),
    C("crooked_signpost", "The Crooked Signpost", "square", "signpost", ("near", 110, 162), 12, ["maps", "signs", "humour"],
      "a leaning signpost with arrows pointing to 'Tomorrow', 'The Edge of the Map' and 'Somewhere Nice'",
      ["'Tomorrow' points east. That seems right.",
       "A new arrow has appeared: 'Kimi's Favourite Place'. It points at the Shrub.",
       "The signpost turns a little each night; the arrows are never quite where they were."]),
    C("chalk_map", "The Chalk Map", "square", "chalk_map", ("near", -60, 155), 30, ["maps", "chalk", "art"],
      "a chalk drawing of Bramblewick on the cobbles that somehow redraws itself every week",
      ["It's very accurate, right down to the Moss Armchair.",
       "This week there's a new place at the edge of the lake, with a question mark.",
       "In the corner, very small, someone has drawn a blue bird."]),
    C("thanks_bench", "The Bench of Small Thanks", "square", "carved_bench", ("near", 250, 165), 16, ["kindness", "wood", "words"],
      "a wooden bench carved all over with tiny thank-yous from the people of Bramblewick",
      ["'Thank you for the umbrella.' 'Thank you for the soup.' 'Thank you for listening.'",
       "There's one blank spot left, just the right size for a wren's thank-you.",
       "Kimi scratches a tiny feather mark there. It feels important."]),
    C("pigeon_post", "The Pigeon Post Box", "square", "post_box", ("near", 150, 152), 10, ["letters", "pigeons", "messages"],
      "a red post box where messages are left for the pigeons to deliver anywhere in town",
      ["The slot is shaped like a beak.",
       "The pigeons keep a strict timetable, written in crumbs.",
       "Inside is a letter addressed simply: 'To whoever feeds the ducks.'"]),
    C("lost_umbrella", "The Lost Umbrella", "square", "umbrella", ("near", -130, 168), 14, ["rain", "weather", "lost things"],
      "a striped umbrella left open near the fountain that opens itself whenever it rains",
      ["It's been there for weeks and nobody claims it.",
       "Under it there's always one dry, warm spot, perfect for a small bird.",
       "When the wind blows it turns slowly, as if looking for someone."]),
    C("fountain_coin", "The Fountain's Bird Coin", "square", "coin", ("attach", 30, 26), 6, ["coins", "fountains", "birds"],
      "a little gold coin at the bottom of the fountain with a bird stamped on it",
      ["It shines brightest at noon.",
       "The bird on it has a cocked tail, just like a wren.",
       "Nobody has ever tried to take it. It seems to belong there."]),

    # --- The Cafe ------------------------------------------------------------------------
    C("teapot_mailbox", "The Teapot Mailbox", "cafe", "teapot_post", ("near", 70, 180), 12, ["tea", "letters", "Marigold"],
      "Marigold's mailbox, a big blue teapot on a post; letters go in through the lid",
      ["The newspaper goes in the spout.",
       "On cold mornings it steams slightly. Nobody knows why.",
       "Marigold says it once held a letter that took forty years to arrive."]),
    C("recipe_board", "The Secret Recipe Board", "cafe", "chalkboard", ("near", 40, 170), 12, ["codes", "food", "recipes"],
      "a chalkboard by the cafe door listing Marigold's recipes in a secret code of little pictures",
      ["A leaf, a drop and a sun probably means dandelion tea.",
       "One recipe is just a picture of a cloud. Kimi would love to taste a cloud.",
       "Kimi cracks a line: 'Seed cake: three hops of millet, one wink of honey.'"]),
    C("crumb_birdbath", "The Birdbath of Crumbs", "cafe", "birdbath", ("near", -70, 180), 14, ["food", "birds", "kindness"],
      "a stone birdbath where Marigold leaves crumbs every morning for anyone with wings",
      ["Today: toast crumbs and one whole sunflower seed.",
       "The sparrows queue very politely.",
       "Carved on the rim: 'For K.' Kimi feels very looked after."]),
    C("jam_pyramid", "The Jam Jar Pyramid", "cafe", "jar_pyramid", ("near", 112, 170), 16, ["jam", "colours", "food"],
      "a pyramid of jam jars stacked outside the cafe, every jar a different colour",
      ["There are twenty-one jars. The top one is the colour of a sunset.",
       "One jar is labelled 'Thunderstorm Jam (do not shake)'.",
       "In the evening light the whole pyramid glows like stained glass."]),
    C("delivery_bicycle", "The Delivery Bicycle", "cafe", "bicycle", ("near", -112, 175), 16, ["bicycles", "honey", "Marigold"],
      "Marigold's old bicycle with a wicker basket that still smells of honey cake",
      ["The bell plays two notes instead of one.",
       "A small cushion is tied into the basket, just the right size for a passenger.",
       "The tyres are patched with tiny squares of tea towel."]),
    C("herb_patch", "The Herb Patch", "cafe", "herb_patch", ("near", 150, 185), 22, ["herbs", "tea", "plants"],
      "a little patch of mint, thyme and dandelions that Marigold grows for her teas",
      ["Hopping through it releases a cloud of minty smell.",
       "A tiny scarecrow made from a teaspoon guards the thyme.",
       "One plant is labelled only: 'Do not pick. Thinking.'"]),

    # --- The Print Shop -----------------------------------------------------------------------
    C("wooden_letters", "The Giant Wooden Letters", "print_shop", "big_letters", ("near", 72, 170), 20, ["letters", "printing", "words"],
      "wooden printing letters taller than Kimi leaning against the wall: K, W, E and a backwards S",
      ["They smell of ink and old wood.",
       "Arranged right they spell 'WEEK', or, with Kimi standing in the middle, 'WEEK-I'.",
       "The backwards S came from a press that printed only in mirror-writing."]),
    C("ink_puddle", "The Ink Puddle", "print_shop", "puddle", ("near", -112, 170), 18, ["ink", "maps", "dreams"],
      "a black puddle of ink that never dries, shaped like a map of somewhere nobody has been",
      ["Its shape changes very slowly, like a coastline.",
       "When the sun is low, tiny silver words float on its surface.",
       "Kimi thinks it might be a map of a dream."]),
    C("stuck_kite", "The Stuck Kite", "print_shop", "kite_pole", ("near", 150, 205), 14, ["kites", "wind", "messages"],
      "a paper kite tangled high on a tall pole, with a message written along its tail",
      ["The message reads: 'If you find this, the wind is your friend.'",
       "The kite is made from an old newspaper page about a flying fish.",
       "On windy days it tugs at the pole as if it wants to keep going."], tall=True),
    C("press_wheel", "The Old Press Wheel", "print_shop", "wheel_planter", ("near", -150, 180), 16, ["printing", "history", "flowers"],
      "the cast-iron wheel from the town's first printing press, now planted with nasturtiums",
      ["The flowers grow in a perfect circle around the spokes.",
       "Stamped on the rim: 'Bramblewick Press, Est. Long Ago'.",
       "Spin it and it clicks out the rhythm of a printing press."]),
    C("poster_wall", "The Poster Wall", "print_shop", "poster_board", ("near", 112, 185), 16, ["posters", "events", "humour"],
      "a board layered with posters for events that never quite happened, like the Great Snail Race of Last Tuesday",
      ["'Moonlight Picnic. Bring Your Own Moon.'",
       "'Lost: one echo. Answers to Hello.'",
       "Under all the others, the very first poster is for a concert by the Spider Harp."]),
    C("paint_steps", "The Paint Pot Steps", "print_shop", "pot_steps", ("near", -72, 195), 24, ["colours", "paint", "games"],
      "old paint pots turned upside down into stepping stones in every colour of the rainbow",
      ["Hopping on them in order, red, orange, yellow, makes Kimi feel very clever.",
       "The green one wobbles.",
       "Someone has added a new silver pot at the end. Where does it lead?"]),

    # --- The Library -----------------------------------------------------------------------------
    C("brass_telescope", "Professor Quill's Telescope", "library", "telescope", ("near", -70, 190), 16, ["stars", "astronomy", "Professor Quill"],
      "a brass telescope on a tripod that Professor Quill points at the same star every night",
      ["The star is labelled in Quill's tiny writing: 'Not yet named.'",
       "Through the eyepiece, even by day, Kimi can see the Shrine's chimes very clearly.",
       "Quill says that star is where lost things go. Kimi thinks of the mitten."]),
    C("little_library", "The Little Free Library", "library", "book_box", ("near", 72, 185), 12, ["books", "reading", "sharing"],
      "a birdhouse-sized bookshelf on a post, full of tiny books anyone can borrow",
      ["Today's titles include 'Puddles and How to Jump' and 'A Short History of Crumbs'.",
       "Every book has a pressed flower for a bookmark.",
       "One book is blank, with a note: 'For your own story.'"]),
    C("planet_orrery", "The Planet Orrery", "library", "orrery", ("near", 122, 190), 16, ["planets", "astronomy", "brass"],
      "a brass model of the planets on a stand that turns slowly all by itself",
      ["There's one planet more than Kimi expected.",
       "The extra planet is painted the exact blue of Kimi's feathers.",
       "It turns faster when it's about to rain."]),
    C("reading_rock", "The Reading Rock", "library", "flat_rock", ("near", -130, 185), 18, ["reading", "stones", "sunshine"],
      "a smooth, sun-warmed rock shaped perfectly for reading on",
      ["There's a hollow just the size of a book.",
       "Generations of readers have polished it smooth.",
       "From here you can hear the Library clock ticking, which helps with concentrating."]),
    C("cracked_globe", "The Cracked Globe", "library", "globe_stand", ("near", 160, 175), 12, ["maps", "geography", "mystery"],
      "an old globe on a wooden stand, cracked across one ocean, showing a country nobody can find in any atlas",
      ["The mystery country is called 'Hush'.",
       "Its shape is exactly the shape of the ink puddle by the Print Shop.",
       "Professor Quill pretends to know nothing about it. Kimi doesn't believe him."]),
    C("inkwell_fountain", "The Inkwell Fountain", "library", "inkwell", ("near", -160, 165), 14, ["writing", "fountains", "words"],
      "a stone fountain shaped like a giant inkwell, with a carved quill sticking out of it",
      ["Rainwater collects in it, faintly blue.",
       "Carved around the rim: 'Write it down, or it flies away.'",
       "Kimi dips a feather and writes 'Kimi' on the stone. It fades slowly, like a secret."]),

    # --- The lily pond --------------------------------------------------------------------------------
    C("frog_throne", "The Frog Throne", None, "lily_pad", ("pond", 30, 42), 12, ["frogs", "pond", "royalty"],
      "the biggest lily pad on the pond, where the same solemn frog always sits",
      ["Kimi decides the frog's name is Sir Ribble.",
       "He croaks exactly twice whenever Kimi says hello.",
       "A tiny crown-shaped flower grows at the edge of the pad."]),
    C("walnut_boat", "The Walnut Boat", None, "walnut_boat", ("pond", 160, 55), 10, ["boats", "pond", "adventure"],
      "a walnut-shell boat with a leaf sail, drifting slowly around the pond",
      ["Painted on the side: 'The Brave Little Nut'.",
       "It always drifts back to the same spot by morning.",
       "A beetle captain stands at the helm, very serious."]),
    C("wobbly_stones", "The Wobbly Stepping Stones", None, "stepping_stones", ("pond", 90, 0), 12, ["stones", "pond", "balance"],
      "a line of stepping stones across the pond; the middle one wobbles",
      ["Kimi crosses without falling in. Mostly.",
       "Under the wobbly stone, something glints.",
       "It's a key-shaped pebble. It doesn't open anything. Yet."]),
    C("reed_flutes", "The Reed Flutes", None, "reeds", ("pond", 215, 96), 16, ["music", "reeds", "wind"],
      "a clump of hollow reeds at the pond's edge that whistle when the wind blows across them",
      ["Each reed plays one note.",
       "When the wind is just right, they play the chimes' three-note tune.",
       "Kimi blows across one and makes a very small, very proud toot."]),

    # --- The island beyond town ---------------------------------------------------------------------------
    C("little_lighthouse", "The Little Lighthouse", None, "lighthouse", ("shore", 205), 26, ["lighthouses", "lake", "codes"],
      "a tiny striped lighthouse on the shore whose light blinks a pattern nobody has ever decoded",
      ["Long, short, short, long. Over and over.",
       "The door is too small for anyone but a bird or a mouse.",
       "Kimi decodes it at last: it blinks the shape of the Seven Stones."], tall=True),
    C("windmill", "The Windmill on Hollow Hill", None, "windmill", ("hill", 35, 1015), 34, ["windmills", "wind", "hills"],
      "an old windmill on the hills whose sails turn even when there's no wind at all",
      ["Inside it smells of flour and old summers.",
       "The sails creak a slow rhythm, like breathing.",
       "From its doorstep you can see all of Bramblewick at once."], tall=True),
    C("message_bottle", "The Message in a Bottle", None, "bottle", ("shore", 300), 10, ["letters", "lake", "mystery"],
      "a green glass bottle washed up on the shore with a rolled-up letter inside",
      ["The letter is rolled too tightly to read through the glass.",
       "Kimi can just make out one word: 'Bramblewick'.",
       "Someone has answered it: a second bottle with a red cork lies beside it."]),
    C("upturned_rowboat", "The Upturned Rowboat", None, "rowboat", ("shore", 140), 24, ["boats", "crabs", "lake"],
      "an old rowboat lying upside down on the shore, now home to a family of crabs",
      ["The crabs have built a little porch out of shells.",
       "The boat's name is half worn away: '…ing Wren'.",
       "Carved under the seat: 'For finding the far shore.'"]),
    C("treehouse", "The Abandoned Treehouse", None, "treehouse", ("hill", 125, 965), 34, ["treehouses", "secret places", "maps"],
      "a treehouse with a rope ladder and a sign saying 'Members Only (Birds Welcome)'",
      ["Inside: a chair, a jar of buttons and a map of the stars.",
       "The guestbook's last entry is a feather. Kimi adds one too.",
       "From the window you can see the lighthouse blink."], tall=True),
    C("friendly_scarecrow", "The Friendly Scarecrow", None, "scarecrow", ("hill", 245, 925), 18, ["scarecrows", "birds", "friends"],
      "a scarecrow in a battered straw hat that every bird in town uses as a perch",
      ["Its button eyes don't match: one blue, one brown.",
       "Someone knitted it a scarf in exactly the red of the lost mitten.",
       "Birds leave it small gifts: a feather, a seed, a shiny clip."], tall=True),
    C("bee_skep", "The Bee Skep", None, "skep", ("hill", 75, 945), 14, ["bees", "honey", "flowers"],
      "a woven straw beehive on a stand, humming with busy bees",
      ["The bees dance a map of the best flowers.",
       "The honey in Marigold's crumpets comes from here.",
       "When Kimi hums, the bees hum louder, as if they're answering."]),
    C("fallen_star", "The Fallen Star", None, "glow_rock", ("hill", 310, 955), 12, ["stars", "stones", "night"],
      "a smooth stone that glows faintly at night, found exactly where a shooting star once landed",
      ["It's warm, like a cup of tea.",
       "It glows brighter on clear nights, as if it misses the sky.",
       "At midnight Professor Quill's unnamed star sits right above it."]),
    C("hollow_log", "The Hollow Log Tunnel", None, "log", ("hill", 170, 905), 30, ["logs", "moss", "tunnels"],
      "a fallen log you can walk right through, lined with moss and tiny mushrooms",
      ["Halfway through, the echo of your steps changes.",
       "Someone has carved little arrows inside pointing both ways.",
       "At night glow-worms turn it into a tunnel of stars."]),
    C("gate_to_nowhere", "The Gate to Nowhere", None, "lone_gate", ("hill", 268, 885), 20, ["gates", "mystery", "meadows"],
      "a garden gate standing all alone in a meadow, with no fence on either side",
      ["It creaks when you open it, even though you could just walk around.",
       "Walking through it feels slightly different from walking around it.",
       "Kimi always goes through. It seems polite."]),
    C("smiling_rock", "The Smiling Rock", None, "boulder", ("hill", 2, 1005), 30, ["stones", "moss", "faces"],
      "a big boulder with patches of moss and lichen that look exactly like a smile",
      ["In the rain the smile looks even happier.",
       "It faces the sunrise every morning.",
       "Kimi sits on top and smiles back. It's only fair."]),
    C("forgotten_picnic", "The Forgotten Picnic", None, "picnic", ("hill", 335, 925), 22, ["picnics", "mystery", "food"],
      "a checked picnic blanket on the hillside with a basket, as if someone just stepped away",
      ["The basket holds an apple, a book and a note: 'Back soon.'",
       "The note has been there for days, but the apple is still fresh.",
       "Kimi guards the picnic until sunset. Nobody comes, but it feels kind to wait."]),
    C("fish_weathervane", "The Fish Weathervane", None, "weathervane", ("hill", 100, 870), 12, ["weather", "fish", "copper"],
      "a copper weathervane shaped like a fish that always points towards the lake, whatever the wind",
      ["Its scales are green with age.",
       "On calm days it wobbles, as if swimming.",
       "Kimi is fairly sure it once winked."], tall=True),
)

BY_ID: dict[str, Curiosity] = {c.id: c for c in CURIOSITIES}
IDS: tuple[str, ...] = tuple(BY_ID)


def catalogue_text(place_name) -> str:
    """Compact catalogue for Kimi's system prompt (static, so it caches)."""
    from .curio3d import curiosity_spots

    spots = curiosity_spots()
    lines = []
    for c in CURIOSITIES:
        zone = spots[c.id]["zone"]
        lines.append(f"- [{c.id}] {c.name} (near {place_name(zone)}): {c.what}.")
    return "\n".join(lines)


def detail_for(curiosity: Curiosity, visit_number: int) -> str:
    """The detail uncovered on the given visit (1-based)."""
    if visit_number <= len(curiosity.details):
        return curiosity.details[visit_number - 1]
    return f"It's as wonderful as ever. {curiosity.details[(visit_number - 1) % len(curiosity.details)]}"

"""Character screen: who Kimi is and who it is becoming."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..world.locations import LOCATIONS
from . import theme
from .widgets import Card, NeedBar, esc, kimi_pixmap, label


def _bullets(items: list[str], empty: str) -> str:
    if not items:
        return f"<i>{esc(empty)}</i>"
    return "".join(f"<p style='margin:2px 0'>• {i}</p>" for i in items)


class CharacterPage(QWidget):
    def __init__(self, runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rt = runtime
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("Page")
        scroll.setWidget(body)
        grid = QGridLayout(body)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        # Identity
        ident = Card()
        top = QHBoxLayout()
        pic = QLabel()
        pic.setPixmap(kimi_pixmap(96, theme.tokens().surface_alt))
        pic.setAccessibleName("Portrait of Kimi")
        top.addWidget(pic)
        names = QVBoxLayout()
        self.name = label("Kimi", heading=True, role="display")
        self.species = label("", muted=True)
        self.age = label("")
        self.mood = label("")
        for w in (self.name, self.species, self.age, self.mood):
            names.addWidget(w)
        top.addLayout(names, 1)
        wrap = QWidget()
        wrap.setLayout(top)
        top.setContentsMargins(0, 0, 0, 0)
        ident.add(wrap)
        grid.addWidget(ident, 0, 0, 1, 2)

        self.traits_card = Card("Personality")
        self.trait_box = QVBoxLayout()
        holder = QWidget()
        holder.setLayout(self.trait_box)
        self.trait_box.setContentsMargins(0, 0, 0, 0)
        self.traits_card.add(holder)
        self.traits_card.add(label("Traits drift slowly - at most a little each day - as Kimi lives.", role="caption", muted=True))
        grid.addWidget(self.traits_card, 1, 0)

        self.interests_card = Card("Interests")
        self.interest_box = QVBoxLayout()
        holder2 = QWidget()
        holder2.setLayout(self.interest_box)
        self.interest_box.setContentsMargins(0, 0, 0, 0)
        self.interests_card.add(holder2)
        self.developing = label("")
        self.interests_card.add(self.developing)
        grid.addWidget(self.interests_card, 1, 1)

        self.prefs = Card("Favourites and preferences")
        self.prefs_text = label("")
        self.prefs.add(self.prefs_text)
        grid.addWidget(self.prefs, 2, 0)

        self.goals = Card("Personal goals")
        self.goals_text = label("")
        self.goals.add(self.goals_text)
        grid.addWidget(self.goals, 2, 1)

        self.opinions = Card("Opinions")
        self.opinions_text = label("")
        self.opinions.add(self.opinions_text)
        grid.addWidget(self.opinions, 3, 0)

        self.collection = Card("Treasures Kimi has found")
        self.collection_text = label("")
        self.collection.add(self.collection_text)
        grid.addWidget(self.collection, 3, 1)

        self.experiences = Card("Important experiences")
        self.exp_text = label("")
        self.experiences.add(self.exp_text)
        grid.addWidget(self.experiences, 4, 0, 1, 2)
        grid.setRowStretch(5, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self._trait_bars: dict[str, NeedBar] = {}
        self._interest_bars: list[NeedBar] = []

    def refresh(self) -> None:
        with self.rt.lock:  # the world thread may be updating the character sheet
            self._refresh()

    def _refresh(self) -> None:
        rt = self.rt
        d = rt.character.snapshot()
        day = rt.world.env.day
        self.name.setText(d["name"])
        self.species.setText(d["species"].capitalize())
        self.age.setText(f"Has lived in Bramblewick for {max(1, day - d.get('born_day', 1) + 1)} day(s).")
        self.mood.setText(f"Feeling <b>{esc(d['mood']['label'])}</b>")

        for trait, value in sorted(d["traits"].items(), key=lambda kv: -kv[1]):
            bar = self._trait_bars.get(trait)
            if bar is None:
                bar = NeedBar(trait.capitalize(), "curiosity")
                self._trait_bars[trait] = bar
                self.trait_box.addWidget(bar)
            word = "very" if value >= 0.75 else "quite" if value >= 0.55 else "a little" if value >= 0.35 else "hardly"
            bar.set_value(value * 100, word)

        interests = rt.character.top_interests(7)
        while len(self._interest_bars) < len(interests):
            bar = NeedBar("", "happiness")
            self._interest_bars.append(bar)
            self.interest_box.addWidget(bar)
        for i, bar in enumerate(self._interest_bars):
            if i < len(interests):
                topic, strength = interests[i]
                bar.name = topic.capitalize()
                bar.setAccessibleName(topic)
                bar.set_value(strength * 100, "strong" if strength >= 0.6 else "growing" if strength >= 0.35 else "new")
                bar.show()
            else:
                bar.hide()
        dev = rt.character.developing_interests(day)
        self.developing.setText("<b>Developing:</b> " + (", ".join(esc(t) for t, _ in dev) if dev else "<i>nothing new this week</i>"))

        def names(table: str) -> str:
            items = rt.character.favourites(table, 4)
            if table == "location_affinity":
                items = [LOCATIONS[i].name if i in LOCATIONS else i for i in items]
            return ", ".join(esc(i.replace("_", " ")) for i in items) or "<i>still deciding</i>"

        weather = d.get("weather_feelings", {})
        weather_txt = ", ".join(f"{esc(k)} ({'likes' if v > 0.45 else 'dislikes' if v < 0.1 else 'neutral'})"
                                for k, v in weather.items()) or "<i>no strong feelings yet</i>"
        self.prefs_text.setText(
            f"<p><b>Places:</b> {names('location_affinity')}</p>"
            f"<p><b>Activities:</b> {names('activity_affinity')}</p>"
            f"<p><b>Foods:</b> {names('food_preferences')}</p>"
            f"<p><b>Weather:</b> {weather_txt}</p>"
        )
        goals = []
        for g in d["goals"][-10:]:
            mark = "✓" if g["status"] == "completed" else "○"
            prog = f" <span style='color:{theme.tokens().ink_muted}'>[{g.get('progress', 0)}/{g['target']}]</span>" if g.get("target") else ""
            goals.append(f"{mark} {esc(g['text'])}{prog}")
        self.goals_text.setText(_bullets(goals, "No goals at the moment."))
        self.opinions_text.setText(_bullets(
            [f"<b>{esc(o['subject'])}:</b> {esc(o['opinion'])} <span style='color:{theme.tokens().ink_muted}'>(Day {o['day']})</span>"
             for o in reversed(d["opinions"][-8:])],
            "Kimi hasn't formed strong opinions yet.",
        ))
        finds = rt.db.query("SELECT item, rarity, location FROM discoveries ORDER BY id DESC LIMIT 8")
        self.collection_text.setText(_bullets(
            [f"{esc(f['item'])} <span style='color:{theme.tokens().ink_muted}'>({f['rarity']}, {esc(LOCATIONS[f['location']].name if f['location'] in LOCATIONS else f['location'])})</span>"
             for f in finds],
            "Nothing yet - Kimi will find things while exploring.",
        ))
        exps = rt.ltm.important_experiences(6)
        self.exp_text.setText(_bullets([esc(m.description) for m in exps],
                                       "Important experiences appear here after Kimi's nightly reflection."))

"""A little humour for the kitchen reminders, with a Ghanaian kitchen accent.

Every reminder keeps its plain facts; a joke only goes in front of them. The joke is picked from
the date and the situation (not at random), so it stays the same all day: on the phone, in the
app and in the Telegram message, and it doesn't change every time the screen redraws.

Teasing is about the food and the pots, never about a person.
"""
import hashlib

LINES = {
    "prep": [
        "The beans won't soak themselves.",
        "Future you will say thank you.",
        "Even the best {dish} starts the day before.",
        "Ten minutes now saves a hungry, cross house later.",
        "Your grandmother would have done this yesterday.",
        "{dish} doesn't make itself, but you can give it a head start.",
    ],
    "leftovers": [
        "No cooking needed: the fridge has your back.",
        "Leftovers today, so the gas cylinder gets a rest.",
        "Day-two {dish} always tastes better anyway.",
        "Heat it, eat it, wash one pot. Simple.",
    ],
    "missing": [
        "The pot is ready. The {item}? Still at the market.",
        "No {item}, no {dish}. That's the law.",
        "You can't cook {dish} with good intentions alone.",
        "Catch the market woman before she packs up: {dish} is counting on you.",
        "The recipe is willing, but the pantry is weak.",
    ],
    "eat_soon": [
        "The {dish} is giving 'eat me today' energy.",
        "Don't let it become a science project at the back of the fridge.",
        "Eat it now, or the dustbin eats it later.",
        "Waste not: that {dish} didn't cook itself.",
    ],
    "past": [
        "Smell first. Then think. Then probably say goodbye.",
        "When in doubt, throw it out.",
    ],
    "low_portions": [
        "Almost finished, so somebody will have to share.",
        "The last spoon is always the sweetest. Fight nicely.",
    ],
    "low_stock": [
        "The pantry is starting to echo.",
        "Don't wait until the pot is already on the fire.",
        "Restock now, before someone shouts 'there's no rice!' at 7 pm.",
    ],
    "nothing_planned": [
        "Nothing planned. Who's cooking? Don't all answer at once.",
        "An empty plan is how supper turns into kelewele from the roadside.",
        "No plan, no pot. Pick something.",
    ],
    "all_ready": [
        "Everything's in. All that's missing is the cook.",
        "Pantry: ready. Pot: ready. Chef: please report to the kitchen.",
    ],
    "budget_75": [
        "The food budget is starting to sweat.",
        "Easy on the extra fish: the budget is watching.",
    ],
    "budget_90": [
        "The food budget is on its last few cedis.",
        "Maybe a simple waakye week, not a party.",
    ],
    "budget_over": [
        "The food budget has left the chat.",
        "Something has to give, and it shouldn't be the rent.",
    ],
}


def joke(kind, day, key="", **fields):
    """The joke for this situation today. Same inputs, same joke.

    Lines can name the dish or item ({dish}, {item}), so the joke is about what's actually short.
    Lines needing a name that wasn't given are skipped."""
    options = []
    for line in LINES.get(kind, []):
        try:
            options.append(line.format(**fields))
        except (KeyError, IndexError):
            continue
    if not options:
        return ""
    seed = hashlib.sha256(f"{day}|{kind}|{key}".encode()).digest()
    out = options[seed[0] % len(options)]
    return out[0].upper() + out[1:]


def with_joke(kind, text, day, key="", on=True, **fields):
    """'<joke> <fact>' when fun reminders are on, otherwise just the fact."""
    if not on:
        return text
    j = joke(kind, day, key, **fields)
    return f"{j} {text}" if j else text

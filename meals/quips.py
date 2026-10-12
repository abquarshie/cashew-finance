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
        "Even the best jollof starts the day before.",
        "Ten minutes now saves a hungry, cross house later.",
        "Your grandmother would have done this yesterday.",
        "A frozen fish has never fried itself.",
    ],
    "leftovers": [
        "No cooking needed: the fridge has your back.",
        "Leftovers today, so the gas cylinder gets a rest.",
        "Day-two stew always tastes better anyway.",
        "Heat it, eat it, wash one pot. Simple.",
    ],
    "missing": [
        "The pot is ready but the ingredients are still at the market.",
        "No onions, no stew. That's the law.",
        "You can't cook jollof with good intentions alone.",
        "Catch the market woman before she packs up.",
        "The recipe is willing, but the pantry is weak.",
    ],
    "eat_soon": [
        "This one is giving 'eat me today' energy.",
        "Don't let it become a science project at the back of the fridge.",
        "Eat it now, or the dustbin eats it later.",
        "Waste not: that stew didn't cook itself.",
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


def joke(kind, day, key=""):
    """The joke for this situation today. Same inputs, same joke."""
    options = LINES.get(kind)
    if not options:
        return ""
    seed = hashlib.sha256(f"{day}|{kind}|{key}".encode()).digest()
    return options[seed[0] % len(options)]


def with_joke(kind, text, day, key="", on=True):
    """'<joke> <fact>' when fun reminders are on, otherwise just the fact."""
    if not on:
        return text
    j = joke(kind, day, key)
    return f"{j} {text}" if j else text

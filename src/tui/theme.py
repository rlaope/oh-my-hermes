"""The OMH TUI's colours, by role, from the same palettes `omh theme` ships.

Every renderer asks for a role (`theme.muted`, `theme.tool`, `theme.diff_add`,
`theme.syntax_keyword`) instead of a colour, so a palette change is one lookup
and no renderer knows a hex value. The palettes are the shipped skin files
read through `skin_pack.skin_colors`; a key a palette lacks falls back to the
default palette's value, so a partial skin still paints every role. Keywords
are bold and comments italic as well as coloured, so the `mono` palette, whose
keyword and text colours nearly match, still tells them apart.

The terminal's background decides the rest. Body text (`text`, `user`, the
reply) and a tool call's name (`tool`, bold) have no colour of their own: they
are the terminal's default foreground, which is readable on whatever
background the person chose. Every other role is measured against that background
(`build_theme(skin, background)`: the colour the terminal reported, or the
palette's status-bar background, the dark stand-in, when it reported none).
A role a person reads as text reaches WCAG's 4.5:1 (`TEXT_ROLES`); a role
drawn only as a glyph or an edge (`dim`, the composer rule and prompt mark)
reaches the 3:1 a graphical mark needs. Each starts from the palette's own
colour and only moves toward the ink (the palette's `banner_text` on a dark
background, black on a light one) as far as that takes, so a palette that
already clears the background keeps its colour. On a light background the
diff bands are tints of the palette's word colours over the background, so
the default foreground stays readable on them; a dark diff band names its own
text colour (`banner_text`), since the dark it assumes may be a guess. `dim` is
for decoration glyphs; words go on `muted` or `hint`.

Hue is kept for what it says (owner's pick of 2026-10-22, the rail with kind
colours), so the transcript's words are neutral grey: a call's arguments on
`muted`, the dimmer duration and what it printed on `faint` (and `hint`), its
glyphs on `dim`, each lifted from a fixed neutral grey (`NEUTRAL_GREYS`) toward
white or black only as far as its floor takes. The chrome around them is the
launch look's (owner's pick of 2026-10-29, `with_launch_look`, the roles in
`LOOK_ROLES`): the composer's rules and every frame drawn in `rule` take the
look's card-edge colour, and a tool call's rail and the working row's spinner
(`accent`) its label colour, each lifted to 3:1. State is hue: `running`, a running call and everything that says a
turn or an agent is running, is the owner's approved blue (`RUNNING_BLUE`,
lifted to 4.5:1), `ok` green and `error` red; nothing else is drawn in it. What only needs to stand out without a
state (a key, a question's mark, a list bullet, a diff hunk) is bold in the
terminal's foreground (`user`) or grey (`muted`). The palette's own accent
is the banner title's alone (`brand`). A call's name is
drawn in its tool family's hue (`kinds`, in `KIND_FAMILIES` order, from
`KIND_HUES`), kept clear of every state hue, and a `/name` that resolves to a
command or skill takes the skill hue, bold (`slash`).

Outcomes sit on bands (`ok_band` behind what the person allowed,
`error_band` behind a denial or a failure): light tints of the palette's diff
colours on a light background, its dark diff colours on a dark one, and
none when no background was reported. What is drawn on a band takes
`on_band(theme, band)`, the roles measured against that band, so its words
reach 4.5:1 and its marks 3:1 on it.

The delegation view's edges step through a gradient (`dag_edges`, from the
top of the drawing to the bottom): the palette's `dag_edge_start`,
`dag_edge_mid` and `dag_edge_end` when it names them, else the violet, indigo
and blue of `DAG_EDGE_STOPS`. Each step is a graphical mark, so it is lifted to
3:1 like `dim`: toward black on a light background, toward the palette's light
ink on a dark one, never the other way. `dag_words` are the same steps lifted
to 4.5:1, for the words a box draws in its state's hue (its title and status).

The pager's footer sits on a bar of its own (`status`): the palette's
status-bar background on a dark terminal or one that reported none, and on
a light one a light tint of that colour (`LIGHT_STATUS_SHARE`), so the bar
belongs to a light screen instead of being a dark band across it. Its words
are measured against that bar instead of the terminal's background. The
menus (`menu`, `menu_current`: the completion menu, the pickers, choice
prompts, the agent list, the delegation view and the bot board) have no bar
and no fill (owner's pick of 2026-10-27, Claude Code's look): a row ends where
its words do on every background, so a highlight is a pointer (`❯`) and the
highlighted row's name bold in the skill hue (`menu_current`, the `slash`
colour, so a command reads the same in the menu and in the composer), with
every other row in the terminal's foreground (`menu`) and its details on
`muted`. An
approval's choices are the exception: the highlighted one is bold in its tone
on a band of that tone (`pick_error`, `pick_ok`, `pick_warn`, `pick_muted`),
since allowing and denying must not look alike at a glance. The
info line under the composer and the sticky prompt over a running turn have
no bar: their words and marks are measured against the terminal's background
like any transcript row.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from functools import lru_cache

from ..skin_pack import (
    SkinTheme,
    default_theme,
    hex_to_rgb,
    skin_colors,
    skin_logo,
    theme_for_name,
    theme_for_skin_name,
)
from .escapes import strip_escapes
from .style import NO_COLOR, Line, Span, Style

TEXT_CONTRAST = 4.5  # WCAG 2 body text
EDGE_CONTRAST = 3.0  # WCAG 2 non-text: a rule, an edge, a secondary mark
_LIFT_STEPS = 20
BLACK = "#000000"
WHITE = "#FFFFFF"
# The background a forced light theme is measured against when the terminal reported none that is light.
LIGHT_STAND_IN = WHITE
# How far a light background's diff tint moves from the word colour toward the background: the line band and the
# word band inside it.
LIGHT_BAND_SHARE = 0.82
LIGHT_WORD_BAND_SHARE = 0.62
# A light background's status bar: the palette's status-bar colour moved this far toward the background.
LIGHT_STATUS_SHARE = 0.85
# An approval's highlighted choice: its tone moved this far toward the background for the band behind it (on a dark
# background, on a light one), so the band is the tone's tint and the tone itself, lifted, still reads on it. On a
# light background 0.85 left an amber band at 1.08:1, too close to the background to see.
PICK_BAND_SHARE = (0.72, 0.78)
# The delegation view's edge gradient, top to bottom, for a palette that names none of these tokens.
DAG_EDGE_STOPS = {"dag_edge_start": "#8B5CF6", "dag_edge_mid": "#6366F1", "dag_edge_end": "#3B82F6"}
DAG_EDGE_STEPS = 9  # an odd count, so the middle stop is a step of its own
# The roles a person reads as text: each reaches TEXT_CONTRAST against the background. `text`, `user` and `tool`
# are not here because they are the terminal's own foreground.
TEXT_ROLES = (
    "running", "label", "ok", "warn", "error", "thinking", "heading", "code", "link", "quote",
    "syntax_keyword", "syntax_string", "syntax_number", "syntax_comment", "hint", "muted", "faint", "mode_accept",
    "mode_plan", "brand", "slash", "background_word",
)
# The roles drawn only as a glyph or an edge: each reaches EDGE_CONTRAST.
GLYPH_ROLES = ("dim", "rule", "prompt", "accent")
# The transcript's neutral greys, (on a dark background, on a light one): a call's arguments (`muted`), the dimmer
# words under and beside it (`faint`, `hint`, thinking), and its glyphs and the composer's rules (`dim`, `rule`).
NEUTRAL_GREYS = {"muted": ("#9198A1", "#59636E"), "faint": ("#7D8590", "#6E7781"), "glyph": ("#545D68", "#8C959F")}
# The running state's blue (on a dark background, on a light one), the owner's approved shade of 2026-10-22: its own
# colour, apart from the delegation view's edge gradient, which keeps its stops.
RUNNING_BLUE = ("#58A6FF", "#2374C9")
# The tool families a call's name is coloured by, and each family's hue (on a dark background, on a light one).
# Each keeps 23 degrees of OKLCH hue or more from the state hues (running blue, failed red, done green), the
# banner's turquoise and the delegation view's selected violet; tests/test_tui_rail_kinds.py holds each to 4.5:1.
KIND_FAMILIES = ("skill", "shell", "file", "web", "dag")
KIND_HUES = {
    "skill": ("#D58CF0", "#9E58B8"), "shell": ("#E3B341", "#996C00"), "file": ("#F8A87E", "#AB6239"),
    "web": ("#C5DE70", "#687C00"), "dag": ("#F778BA", "#BF4588"),
}
# The aura a `dag-ulw` in the composer takes (`aura`, `aura_glint`): violet, magenta, pink and lavender (on a dark
# background, on a light one), stepped over `AURA_STEPS` across the word and across each rule, and the same steps
# mixed `AURA_GLINT_SHARE` of the way toward a near-white lavender (a deep violet on a light background) for the
# band that sweeps through them.
AURA_STOPS = (("#A77BFF", "#6F3FD6"), ("#D95FE8", "#A3249E"), ("#FF7AB6", "#C2366F"), ("#CDB8FF", "#7354C2"))
AURA_STEPS = 8
AURA_GLINT = ("#F6F0FF", "#2E1470")
AURA_GLINT_SHARE = 0.7
# The least contrast between a step and its band colour, once both are lifted, at which the band still shows. On a
# mid-grey background the lift pulls both to the same ink: the aura is then the still look `NO_COLOR` gets, a bold
# token and heavy rules in the rule colour, and nothing ticks for it (`aura_moves`).
AURA_GLINT_MIN_CONTRAST = 1.15
# The tool families a call's name is coloured by (`Theme.kinds`, in `KIND_FAMILIES` order); a name in none
# keeps the terminal's foreground, bold. Hermes' browser tools all start `browser_`.
TOOL_FAMILIES = {
    "skill": frozenset({"skill_view", "skills_list", "skill_manage", "tool_describe", "tool_search", "tool_call",
                        "todo_list", "memory", "clarify", "session_search"}),
    "shell": frozenset({"terminal", "process", "execute_code"}),
    "file": frozenset({"read_file", "write_file", "patch", "search_files"}),
    "web": frozenset({"web_search", "web_extract"}),
    "dag": frozenset({"delegate_task", "omh_dag", "omh_team"}),
}


# The launch looks (`launch_card`), in the order the /theme picker lists them; the first is the default. Each is the
# block logo's colouring and the card's three colours, on a dark background and on a light one (the same hues at a
# lower OKLCH lightness, rather than the dark set mixed toward black, which greys a tint out). They are OMH's own:
# the skin's `banner_*` keys, which Hermes' own banner reads, stay as the skin file has them.
LAUNCH_PRESETS = ("spectrum", "violet", "gold", "graphite", "sakura", "moonlit", "aurora", "ember")
DEFAULT_LAUNCH = LAUNCH_PRESETS[0]
# The roles a launch look owns beyond the logo and the card (`with_launch_look`): the composer's rules and every frame
# in `rule` (its card-edge colour), a tool call's rail and the working row's spinner (`accent`, its label colour), a
# sent prompt's band (`with_prompt_band`), a catch row and the working glow (`with_catch_colours`). Body text, the
# neutral greys, the state colours (`running`, `ok`, `warn`, `error`) and their bands, the kind hues and the skin's
# own roles (`brand`, `heading`, syntax, diff) stay the skin's, so a look never changes what a colour says.
LOOK_ROLES = ("rule", "accent", "prompt_band", "catch_mark", "catch_words", "glow_ring")


@dataclass(frozen=True)
class LogoPalette:
    """One launch look's colours: the logo's (a ramp per row, a sweep across the columns, or graphite's grey OH-MY-,
    white HERMES and coloured hyphens), then the card's title (`brand`), labels and edges."""

    brand: str
    label: str
    edge: str
    faces: tuple[str, ...] = ()  # one colour per logo row, top first
    sweep: tuple[str, ...] = ()  # stops across the logo's columns, left first
    greys: tuple[str, ...] = ()  # graphite: OH-MY-, per row
    whites: tuple[str, ...] = ()  # graphite: HERMES, per row
    spark: str = ""  # graphite: the two hyphens


LAUNCH_PALETTES: dict[str, tuple[LogoPalette, LogoPalette]] = {
    "spectrum": (
        LogoPalette("#F778BA", "#F8A87E", "#4A4F66",
                    sweep=tuple(KIND_HUES[kind][0] for kind in ("skill", "dag", "file", "shell", "web"))),
        # The kind hues' light column ends in an olive lime (#687C00); the sweep's own light stops keep each hue's
        # chroma instead, the lime at OKLCH 132 degrees.
        LogoPalette("#B53C80", "#BF4306", "#8C93A8", sweep=("#974BB2", "#B53C80", "#BF4306", "#986600", "#4E8302")),
    ),
    "violet": (
        LogoPalette("#D9A8FF", "#D58CF0", "#6E5A85",
                    faces=("#EAE3FF", "#E2C8FF", "#DAAEFA", "#DE93E8", "#E278CF", "#E35AAE")),
        LogoPalette("#7447C8", "#8A3FD1", "#9A8AB4",
                    faces=("#7447C8", "#8843C0", "#9940B6", "#A93CA8", "#B73A98", "#C33887")),
    ),
    "gold": (
        LogoPalette("#F2C14E", "#E5B655", "#7B6540",
                    faces=("#FFEEBB", "#F9DB8E", "#EFC972", "#E5B655", "#DBA334", "#C98A10")),
        LogoPalette("#9A6700", "#925D00", "#A08A5C",
                    faces=("#A77601", "#A06E05", "#996502", "#925D00", "#8B5505", "#844E04")),
    ),
    "graphite": (
        LogoPalette("#F0F6FC", "#C2C8CE", "#3D444D",
                    greys=("#9198A1", "#878E97", "#7D8590", "#737B86", "#6A717C", "#636A74"),
                    whites=("#F0F6FC", "#E3E9EF", "#D3D9DF", "#C2C8CE", "#B1B8BF", "#A2A9B0"), spark="#00CED1"),
        LogoPalette("#1F2328", "#464B50", "#8C959F",
                    greys=("#7C8186", "#767B80", "#70757A", "#6A6F74", "#65696F", "#5F6469"),
                    whites=("#202429", "#2D3135", "#393E42", "#464B50", "#54595E", "#62676C"), spark="#008A8D"),
    ),
    # Anime pastel: soft pink into sky blue and cream, at a high OKLCH lightness; the rails sky blue.
    "sakura": (
        LogoPalette("#FC9CBD", "#7AC8F5", "#734A5A", sweep=("#FF99BD", "#E5AEE8", "#86C5FA", "#91DBF2", "#F9E6BB")),
        LogoPalette("#C1587D", "#087AAF", "#C69EAC", sweep=("#C85E83", "#9F69A7", "#297AB6", "#2286A7", "#A38951")),
    ),
    # A moonlit night: pale moonlight yellow over silver into deep navy, the card's edge (and so the prompt band) navy.
    "moonlit": (
        LogoPalette("#D5DFEB", "#F2E6A8", "#2D3B62",
                    faces=("#FFF3B5", "#D6E7F8", "#C0CBDF", "#9CAED5", "#7D93CD", "#677CC2")),
        LogoPalette("#535E6F", "#334889", "#8B98B8",
                    faces=("#91772A", "#576574", "#4B5B77", "#3E517F", "#2E4282", "#26357B")),
    ),
    # Aurora: emerald and teal into violet across the columns; the rails teal, so no chrome reads as the done green.
    "aurora": (
        LogoPalette("#B696F7", "#50D7C3", "#0C5952", sweep=("#5EE38B", "#4FD9B4", "#53D1D0", "#77A4F6", "#AE84F2")),
        LogoPalette("#7145B5", "#0E7A6D", "#73ABA3", sweep=("#108846", "#0C7E65", "#00787D", "#3860AC", "#7541B8")),
    ),
    # Ember: amber at the top through orange to crimson; the rails orange, between the warning amber and failure red.
    "ember": (
        LogoPalette("#FCC270", "#FF8F49", "#70322B",
                    faces=("#FFCF82", "#FFA54B", "#FF7C34", "#F3562E", "#E23532", "#CC2538")),
        LogoPalette("#B3260E", "#B54900", "#CB8D7D",
                    faces=("#A96000", "#B44A00", "#B83300", "#B31609", "#A9001A", "#9A0027")),
    ),
}
# A sent prompt's band: the launch look's card-edge colour moved this far toward the background (on a dark one, on a
# light one), so the band is that look's tint at about 1.2-1.5:1 against the background.
PROMPT_BAND_SHARE = (0.6, 0.8)
# How far the background-process row's `background` word moves from `label` toward the background (owner, 2026-10-28:
# a little darker than the label); it is lifted back to TEXT_CONTRAST where that takes it below.
BACKGROUND_WORD_SHARE = 0.18
LOGO_BLOCK = "█"
# How far a drop-shadow glyph (the logo's box-drawing characters) is pulled from its face colour toward the background.
LOGO_SHADOW_SHARE = 0.55
# A sweep's row shading: the top rows lit (mixed toward white), the bottom rows shaded (toward black).
LOGO_SWEEP_SHADE = {0: (WHITE, 0.30), 1: (WHITE, 0.14), 4: (BLACK, 0.12), 5: (BLACK, 0.26)}


@dataclass(frozen=True)
class Theme:
    name: str
    text: Style
    dim: Style
    running: Style  # a running call, turn or agent, in the approved blue (`RUNNING_BLUE`), and nothing else
    label: Style
    ok: Style
    warn: Style
    error: Style
    tool: Style
    thinking: Style
    rule: Style
    prompt: Style
    user: Style  # bold in the terminal's own foreground: a key, a question's mark, what stands out without a state
    heading: Style
    code: Style
    link: Style
    quote: Style
    diff_add: Style
    diff_add_word: Style
    diff_remove: Style
    diff_remove_word: Style
    syntax_keyword: Style
    syntax_string: Style
    syntax_number: Style
    syntax_comment: Style
    status: Style
    menu: Style  # a menu or picker row's name, unhighlighted: the terminal's foreground, no fill
    menu_current: Style  # the highlighted row's pointer and name: bold in the skill hue (`slash`), no fill
    hint: Style
    muted: Style
    mode_accept: Style
    mode_plan: Style
    ok_band: Style  # behind what the person allowed (an approval)
    error_band: Style  # behind a denial or a failure: a denied approval, a failed tool row and its lines, an error notice
    dag_edges: tuple[Style, ...]  # the delegation view's edges, top layer to bottom (`DAG_EDGE_STEPS` of them)
    dag_words: tuple[Style, ...]  # the same steps lifted to TEXT_CONTRAST: a box's title and status words
    faint: Style  # a call's duration and what it printed, dimmer than its arguments on `muted`
    brand: Style  # the banner's title, bold: the palette's accent, which no other role uses
    kinds: tuple[Style, ...]  # a call's name, bold, in its tool family's hue, in `KIND_FAMILIES` order
    slash: Style  # a `/name` that resolves to a command or skill, bold, in the composer and your prompt's rows
    background_word: Style  # the background-process row's `background` and spinner: bold, `label` a step dimmer
    aura: tuple[Style, ...] = ()  # a `dag-ulw` in the composer and the rules around it, bold, `AURA_STOPS` stepped
    aura_glint: tuple[Style, ...] = ()  # the same steps toward `AURA_GLINT`: the band that sweeps through them
    prompt_band: Style = Style()  # behind a prompt you sent, edge to edge (`with_prompt_band`); none until set
    catch_mark: tuple[Style, ...] = ()  # a catch row's `✦ OMH`, cell by cell, bold, through the launch look's logo
    catch_words: Style = Style()  # what a catch row says: the launch look's label colour (`with_catch_colours`);
    # `build_theme` sets both from the default launch look, so no built theme leaves them unpainted
    accent: Style = Style()  # a tool call's rail (but a failed or denied one's) and the working row's spinner: the
    # launch look's label colour lifted to 3:1 (`with_launch_look`); `build_theme` paints it from the default look
    look: str = DEFAULT_LAUNCH  # the launch look the look's roles (`LOOK_ROLES`) are from, kept by `on_band`
    # The working glow round the screen while a turn runs (`edge_glow`): the launch look's logo colours stepped once
    # round a ring, first back to first (`with_catch_colours`), and the colour they are mixed into toward their dim
    # ends: its `bg` where the terminal reported it, so the glow may paint cells' backgrounds, else its `fg`, a guess.
    glow_ring: tuple[Style, ...] = ()
    glow_surface: Style = Style()
    # An approval's highlighted choice, bold in its tone (deny `error`, an allow `ok`, always `warn`, the tell row
    # `muted`) on a band of that tone mixed into the background (`PICK_BAND_SHARE`); no band when no background was
    # reported. `build_theme` paints all four.
    pick_error: Style = Style()
    pick_ok: Style = Style()
    pick_warn: Style = Style()
    pick_muted: Style = Style()


def aura_moves(theme: Theme) -> bool:
    """Whether the theme's aura has its gradient and band (`AURA_GLINT_MIN_CONTRAST`), or is the still bold look."""
    return bool(theme.aura) and theme.aura[0].fg is not None


def tool_family(name: str) -> str:
    """The family a tool's name belongs to (`TOOL_FAMILIES`), or "" for none."""
    if name.startswith("browser_"):
        return "web"
    return next((family for family, names in TOOL_FAMILIES.items() if name in names), "")


def kind_style(name: str, theme: Theme) -> Style:
    """A call's name: bold, in its family's hue, else in the terminal's foreground."""
    family = tool_family(name)
    return theme.kinds[KIND_FAMILIES.index(family)] if family and theme.kinds else theme.tool


def _channel(value: int) -> float:
    srgb = value / 255
    return srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4


_CHANNELS = tuple(_channel(value) for value in range(256))  # every 8-bit channel's linear light, worked out once


def contrast_ratio(first: str, second: str) -> float:
    """WCAG 2 contrast between two `#rrggbb` colours, 1.0 to 21.0; 1.0 when either is not a plain hex."""
    rgbs = [hex_to_rgb(first), hex_to_rgb(second)]
    if rgbs[0] is None or rgbs[1] is None:
        return 1.0
    return _ratio(_luminance(rgbs[0]), _luminance(rgbs[1]))


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * _CHANNELS[r] + 0.7152 * _CHANNELS[g] + 0.0722 * _CHANNELS[b]


def _ratio(first: float, second: float) -> float:
    lighter, darker = (first, second) if first >= second else (second, first)
    return (lighter + 0.05) / (darker + 0.05)


def _mix(start: str, end: str, share: float) -> str:
    one, two = hex_to_rgb(start), hex_to_rgb(end)
    if one is None or two is None:
        return start
    return "#" + "".join(f"{round(a + (b - a) * share):02X}" for a, b in zip(one, two, strict=True))


@lru_cache(maxsize=4096)
def _lifted(colour: str, toward: str, background: str, minimum: float) -> str:
    """`colour` moved toward `toward` in twentieths until it reaches `minimum` against `background`, and on from
    `toward` to pure black or white, whichever reads better there, where `toward` itself falls short.

    `toward` is the palette's ink on a dark background (`banner_text`), not white. On a mid grey just dark enough
    to take light text, a tinted ink such as crimson's #FFEDE6 reaches only 4.36:1 on #707070, while white reaches
    4.95:1. The better of black and white always reaches 4.58:1 or more, so no `minimum` up to that is out of reach.

    Each step is `_mix` measured by `contrast_ratio`, on channels parsed once rather than per step: a launch logo
    lifts some 600 glyph colours in one paint. Cached, as a theme and every later paint ask the same again.
    """
    back = hex_to_rgb(background)
    floor = None if back is None else _luminance(back)
    for start, target in ((colour, toward), (toward, None)):
        if target is None:  # asked only once `toward` falls short
            target = BLACK if is_light(background) else WHITE
        one, two = hex_to_rgb(start), hex_to_rgb(target)
        if one is None or two is None:  # `_mix` gives `start` back at every step
            if contrast_ratio(start, background) >= minimum:
                return start
            continue
        for step in range(_LIFT_STEPS + 1):
            share = step / _LIFT_STEPS
            rgb = (round(one[0] + (two[0] - one[0]) * share), round(one[1] + (two[1] - one[1]) * share),
                   round(one[2] + (two[2] - one[2]) * share))
            if (1.0 if floor is None else _ratio(_luminance(rgb), floor)) >= minimum:
                return "#" + "".join(f"{value:02X}" for value in rgb)
    return BLACK if is_light(background) else WHITE


def _palette(skin: SkinTheme) -> dict[str, str]:
    base = skin_colors(default_theme().skin_name)
    return {**DAG_EDGE_STOPS, **base, **skin_colors(skin.skin_name)}


def _gradient(stops: list[str], steps: int) -> list[str]:
    """`steps` colours evenly through `stops`, the first stop first and the last stop last."""
    colours = []
    for step in range(steps):
        at = step / (steps - 1) * (len(stops) - 1)
        index = min(int(at), len(stops) - 2)
        colours.append(_mix(stops[index], stops[index + 1], at - index))
    return colours


def is_light(background: str) -> bool:
    """Whether dark text reads better than light text on `background` (`#rrggbb`)."""
    return contrast_ratio(background, BLACK) > contrast_ratio(background, WHITE)


def surface_for(skin: SkinTheme, background: str | None) -> str:
    """What the roles are measured against: `background` when it is a plain hex, else the palette's status-bar background."""
    return background if background and hex_to_rgb(background) else _palette(skin)["status_bar_bg"]


def lifted_colour(colour: str, surface: str, minimum: float, ink: str) -> str:
    """`colour` moved toward `ink` only as far as reaching `minimum` against `surface` takes."""
    return _lifted(colour, ink, surface, minimum)


def build_theme(skin: SkinTheme, background: str | None = None) -> Theme:
    """Map one shipped palette onto the TUI's roles, measured against `background` (see the module docstring)."""
    c = _palette(skin)
    surface = surface_for(skin, background)
    reported = surface == background  # the terminal said what its background is
    light = is_light(surface)
    ink = BLACK if light else c["banner_text"]
    status_bg = _mix(c["status_bar_bg"], surface, LIGHT_STATUS_SHARE) if reported and light else c["status_bar_bg"]

    def read(key: str) -> str:
        return _lifted(c[key], ink, surface, TEXT_CONTRAST)

    side = 1 if light else 0

    def grey(key: str, minimum: float) -> str:
        return _lifted(NEUTRAL_GREYS[key][side], BLACK if light else WHITE, surface, minimum)

    def hue(family: str) -> str:
        return _lifted(KIND_HUES[family][side], ink, surface, TEXT_CONTRAST)

    def mark(key: str) -> str:
        return _lifted(c[key], ink, surface, EDGE_CONTRAST)

    status_ink = BLACK if is_light(status_bg) else c["banner_text"]
    aura_steps = [_lifted(colour, ink, surface, TEXT_CONTRAST)
                  for colour in _gradient([stop[side] for stop in AURA_STOPS], AURA_STEPS)]
    # Each band colour is its lifted step mixed toward `AURA_GLINT`, lifted again: near the background's dark/light
    # flip the step is already near the ink and the mix can pull it back toward the background.
    glint_steps = [_lifted(_mix(colour, AURA_GLINT[side], AURA_GLINT_SHARE), ink, surface, TEXT_CONTRAST)
                   for colour in aura_steps]
    moving = min(contrast_ratio(step, glint) for step, glint in zip(aura_steps, glint_steps, strict=True)) \
        >= AURA_GLINT_MIN_CONTRAST

    def on_bar(key: str, minimum: float = TEXT_CONTRAST) -> Style:
        return Style(fg=_lifted(c[key], status_ink, status_bg, minimum), bg=status_bg)

    def pick(colour: str, toward: str) -> Style:
        if not reported:
            return Style(fg=_lifted(colour, toward, surface, TEXT_CONTRAST), bold=True)
        band = _mix(colour, surface, PICK_BAND_SHARE[side])
        return Style(fg=_lifted(colour, toward, band, TEXT_CONTRAST), bg=band, bold=True)

    if not reported:
        ok_band = error_band = Style()
    elif light:
        ok_band = Style(bg=_mix(c["diff_added_word"], surface, LIGHT_BAND_SHARE))
        error_band = Style(bg=_mix(c["diff_removed_word"], surface, LIGHT_BAND_SHARE))
    else:
        ok_band, error_band = Style(bg=c["diff_added"]), Style(bg=c["diff_removed"])
    if light:
        diff_add = Style(bg=_mix(c["diff_added_word"], surface, LIGHT_BAND_SHARE))
        diff_add_word = Style(bg=_mix(c["diff_added_word"], surface, LIGHT_WORD_BAND_SHARE), bold=True)
        diff_remove = Style(bg=_mix(c["diff_removed_word"], surface, LIGHT_BAND_SHARE))
        diff_remove_word = Style(bg=_mix(c["diff_removed_word"], surface, LIGHT_WORD_BAND_SHARE), bold=True)
    else:
        diff_add = Style(fg=c["banner_text"], bg=c["diff_added"])
        diff_add_word = Style(fg=c["diff_added_word"], bg=c["diff_added"])
        diff_remove = Style(fg=c["banner_text"], bg=c["diff_removed"])
        diff_remove_word = Style(fg=c["diff_removed_word"], bg=c["diff_removed"])
    theme = Theme(
        name=skin.short_name,
        text=Style(),
        dim=Style(fg=grey("glyph", EDGE_CONTRAST)),
        running=Style(fg=_lifted(RUNNING_BLUE[side], ink, surface, TEXT_CONTRAST)),
        label=Style(fg=read("ui_label")),
        ok=Style(fg=read("ui_ok")),
        warn=Style(fg=read("ui_warn")),
        error=Style(fg=read("ui_error")),
        tool=Style(bold=True),
        thinking=Style(fg=grey("faint", TEXT_CONTRAST), italic=True),
        rule=Style(),  # the launch look's (`with_launch_look`, below)
        prompt=Style(fg=mark("prompt"), bold=True),
        user=Style(bold=True),
        heading=Style(fg=read("banner_title"), bold=True),
        code=Style(fg=read("syntax_string")),
        link=Style(fg=read("ui_label"), underline=True),
        quote=Style(fg=read("syntax_comment"), italic=True),
        diff_add=diff_add,
        diff_add_word=diff_add_word,
        diff_remove=diff_remove,
        diff_remove_word=diff_remove_word,
        syntax_keyword=Style(fg=read("syntax_keyword"), bold=True),
        syntax_string=Style(fg=read("syntax_string")),
        syntax_number=Style(fg=read("syntax_number")),
        syntax_comment=Style(fg=read("syntax_comment"), italic=True),
        status=on_bar("status_bar_text"),
        menu=Style(),
        menu_current=Style(fg=hue("skill"), bold=True),
        hint=Style(fg=grey("faint", TEXT_CONTRAST)),
        muted=Style(fg=grey("muted", TEXT_CONTRAST)),
        mode_accept=Style(fg=read("ui_warn")),
        mode_plan=Style(fg=read("ui_ok")),
        ok_band=ok_band,
        error_band=error_band,
        dag_edges=tuple(
            Style(fg=_lifted(colour, ink, surface, EDGE_CONTRAST))
            for colour in _gradient([c[key] for key in DAG_EDGE_STOPS], DAG_EDGE_STEPS)
        ),
        dag_words=tuple(
            Style(fg=_lifted(colour, ink, surface, TEXT_CONTRAST))
            for colour in _gradient([c[key] for key in DAG_EDGE_STOPS], DAG_EDGE_STEPS)
        ),
        faint=Style(fg=grey("faint", TEXT_CONTRAST)),
        brand=Style(fg=read("ui_accent"), bold=True),
        kinds=tuple(Style(fg=hue(family), bold=True) for family in KIND_FAMILIES),
        slash=Style(fg=hue("skill"), bold=True),
        background_word=Style(fg=_lifted(_mix(read("ui_label"), surface, BACKGROUND_WORD_SHARE), ink, surface,
                                         TEXT_CONTRAST), bold=True),
        aura=tuple(Style(fg=colour, bold=True) for colour in aura_steps) if moving else (Style(bold=True),),
        aura_glint=tuple(Style(fg=colour, bold=True) for colour in glint_steps) if moving else (Style(bold=True),),
        pick_error=pick(c["ui_error"], ink),
        pick_ok=pick(c["ui_ok"], ink),
        pick_warn=pick(c["ui_warn"], ink),
        pick_muted=pick(NEUTRAL_GREYS["muted"][side], BLACK if light else WHITE),
    )
    # The default launch look's roles; `with_launch_look` repaints them for the shown one.
    return with_launch_look(theme, skin, background, DEFAULT_LAUNCH)


def launch_palette(name: str, surface: str) -> LogoPalette:
    """The launch look `name`'s colours for `surface` (its light set on a light one); the default look's for an
    unknown name."""
    dark, light = LAUNCH_PALETTES.get(name, LAUNCH_PALETTES[DEFAULT_LAUNCH])
    return light if is_light(surface) else dark


# The mark a catch row opens with, drawn through the launch look's logo colours by the transcript (`Theme.catch_mark`).
# It lives here, not in `panels`, so the approval slot (`prompts`) can draw it without importing `panels`.
CATCH_MARK = "✦ OMH"
# The cells of a catch row's mark (`CATCH_MARK`) the logo's colours are stepped across.
CATCH_MARK_CELLS = 5
# The colours the working glow's ring is stepped through (`Theme.glow_ring`, owner request 2026-10-28).
GLOW_RING_STEPS = 36


def _logo_stops(palette: LogoPalette) -> list[str]:
    """The colours a launch look's logo runs through, first to last: its sweep, its row faces, or graphite's white
    HERMES into its coloured hyphens."""
    if len(palette.sweep) > 1:
        return list(palette.sweep)
    if len(palette.faces) > 1:
        return list(palette.faces)
    return [palette.whites[0] if palette.whites else palette.label, palette.spark or palette.brand]


def with_catch_colours(theme: Theme, skin: SkinTheme, background: str | None, look: str) -> Theme:
    """`theme` with a catch row's colours from launch look `look` (owner's pick of 2026-10-28): the `✦ OMH` mark
    stepped through the logo's colours (`CATCH_MARK_CELLS`), the words in the look's label colour, so the row reads
    as OMH's own and changes with `/theme`. The working glow (`glow_ring`) takes the same logo colours, round a
    ring that comes back to its first, mixed into the background toward its dim ends."""
    surface = surface_for(skin, background)
    palette = launch_palette(look, surface)
    stops = _logo_stops(palette)
    mark = tuple(Style(fg=colour, bold=True) for colour in _gradient(stops, CATCH_MARK_CELLS))
    ring = tuple(Style(fg=colour) for colour in _gradient([*stops, stops[0]], GLOW_RING_STEPS + 1)[:-1])
    reported = surface == background
    ink = BLACK if is_light(surface) else _palette(skin)["banner_text"]
    words = Style(fg=_lifted(palette.label, ink, surface, TEXT_CONTRAST))
    return replace(theme, catch_mark=mark, catch_words=words, glow_ring=ring,
                   glow_surface=Style(bg=surface) if reported else Style(fg=surface))


def with_launch_look(theme: Theme, skin: SkinTheme, background: str | None, look: str) -> Theme:
    """`theme` with the roles launch look `look` owns (`LOOK_ROLES`, owner's pick of 2026-10-29), measured against
    `background`: `rule` from its card-edge colour and `accent` from its label colour, each lifted to the 3:1 a glyph
    needs, then a catch row's and the working glow's colours (`with_catch_colours`). A name OMH does not have is the
    default look, as `launch_palette` reads it. The band behind a sent prompt is `with_prompt_band`'s."""
    surface = surface_for(skin, background)
    ink = BLACK if is_light(surface) else _palette(skin)["banner_text"]
    palette = launch_palette(look, surface)
    looked = replace(theme, look=look if look in LAUNCH_PALETTES else DEFAULT_LAUNCH,
                     rule=Style(fg=_lifted(palette.edge, ink, surface, EDGE_CONTRAST)),
                     accent=Style(fg=_lifted(palette.label, ink, surface, EDGE_CONTRAST)))
    return with_catch_colours(looked, skin, background, look)


def blend(start: str, end: str, share: float) -> str:
    """`#rrggbb` `start` moved `share` (0 to 1) of the way to `end`."""
    return _mix(start, end, share)


def with_prompt_band(theme: Theme, skin: SkinTheme, background: str | None, look: str) -> Theme:
    """`theme` with the band behind a prompt you sent (`prompt_band`, owner's pick of 2026-10-27): launch look
    `look`'s card-edge colour mixed most of the way into the background (`PROMPT_BAND_SHARE`), so each look tints it
    its own way. None when the terminal reported no background, as with the outcome bands: a band guessed for a dark
    screen would be a dark bar across a light one."""
    surface = surface_for(skin, background)
    if surface != background:
        return replace(theme, prompt_band=Style())
    side = 1 if is_light(surface) else 0
    edge = launch_palette(look, surface).edge
    return replace(theme, prompt_band=Style(bg=_mix(edge, surface, PROMPT_BAND_SHARE[side])))


def _logo_hyphens(rows: list[str]) -> set[int]:
    """The columns of the logo's two hyphens: a `█████╗` on the third row over a `╚════╝` on the fourth (an H's
    crossbar has the H's own legs under it instead)."""
    found: set[int] = set()
    if len(rows) < 4:
        return found
    start = rows[2].find("█████╗")
    while start != -1:
        if rows[3][start : start + 6] == "╚════╝":
            found.update(range(start, start + 6))
        start = rows[2].find("█████╗", start + 1)
    return found


def _logo_face(palette: LogoPalette, row: int, col: int, sweep: list[str], hyphens: set[int], split: int) -> str:
    if palette.faces:
        return palette.faces[min(row, len(palette.faces) - 1)]
    if sweep:
        toward, share = LOGO_SWEEP_SHADE.get(row, (WHITE, 0.0))
        return _mix(sweep[min(col, len(sweep) - 1)], toward, share)
    if col in hyphens:
        return palette.spark
    ramp = palette.greys if col < split else palette.whites
    return ramp[min(row, len(ramp) - 1)]


def logo_lines(skin: SkinTheme, background: str | None, palette: LogoPalette) -> list[Line]:
    """The skin's block logo (`skin_pack.skin_logo`) in a launch look's colours, cell by cell, against `background`.

    The skin gives the rows and their bold; `palette` the colours. A block
    glyph takes its face colour; a box-drawing glyph, the drop shadow, takes
    that colour pulled `LOGO_SHADOW_SHARE` toward the background. Every glyph
    is then lifted to the 3:1 a graphical mark needs, as every glyph role is.
    Escape sequences and control characters are taken out of the text, so a
    skin file never writes to the terminal.
    """
    c = _palette(skin)
    surface = surface_for(skin, background)
    ink = BLACK if is_light(surface) else c["banner_text"]
    source = skin_logo(skin.skin_name)
    rows = ["".join(char for char in strip_escapes(text) if char.isprintable()) for text, _colour, _bold in source]
    width = max((len(row) for row in rows), default=0)
    sweep = _gradient(list(palette.sweep), max(width, 2)) if palette.sweep else []
    hyphens = _logo_hyphens(rows)
    split = max(hyphens) + 1 if hyphens else width // 2  # OH-MY- ends with its second hyphen
    lines: list[Line] = []
    for index, (text, (_text, _colour, bold)) in enumerate(zip(rows, source, strict=True)):
        spans: list[Span] = []
        for col, char in enumerate(text):
            face = _logo_face(palette, index, col, sweep, hyphens, split)
            if char not in (LOGO_BLOCK, " "):
                face = _mix(face, surface, LOGO_SHADOW_SHARE)
            style = Style(fg=_lifted(face, ink, surface, EDGE_CONTRAST), bold=bold)
            if spans and spans[-1].style == style:
                spans[-1] = Span(spans[-1].text + char, style)
            else:
                spans.append(Span(char, style))
        lines.append(tuple(spans))
    return lines


def launch_wordmark(text: str, skin: SkinTheme, background: str | None, palette: LogoPalette) -> Line:
    """`text` (the brand) in a launch look's logo colours, a colour per character, each lifted to 4.5:1 and bold:
    the middle row's colour of a ramp, a sweep across the characters, or graphite's grey, turquoise hyphens and
    white."""
    c = _palette(skin)
    surface = surface_for(skin, background)
    ink = BLACK if is_light(surface) else c["banner_text"]
    sweep = _gradient(list(palette.sweep), max(len(text), 2)) if palette.sweep else []
    split = text.rfind("-")
    spans: list[Span] = []
    for index, char in enumerate(text):
        if palette.faces:
            colour = palette.faces[min(2, len(palette.faces) - 1)]
        elif sweep:
            colour = sweep[index]
        elif char == "-":
            colour = palette.spark
        else:
            colour = (palette.greys if index < split else palette.whites)[2]
        spans.append(Span(char, Style(fg=_lifted(colour, ink, surface, TEXT_CONTRAST), bold=True)))
    return tuple(spans)


@dataclass(frozen=True)
class LaunchStyles:
    """A launch look's card colours as styles: its title (bold, 4.5:1), its labels (bold, 4.5:1), its edges (3:1)."""

    brand: Style
    label: Style
    edge: Style


def launch_styles(skin: SkinTheme, background: str | None, palette: LogoPalette) -> LaunchStyles:
    """`palette`'s card colours measured against `background`, lifted only as far as their floors take."""
    c = _palette(skin)
    surface = surface_for(skin, background)
    ink = BLACK if is_light(surface) else c["banner_text"]
    return LaunchStyles(
        brand=Style(fg=_lifted(palette.brand, ink, surface, TEXT_CONTRAST), bold=True),
        label=Style(fg=_lifted(palette.label, ink, surface, TEXT_CONTRAST), bold=True),
        edge=Style(fg=_lifted(palette.edge, ink, surface, EDGE_CONTRAST)),
    )


@lru_cache(maxsize=32)
def on_band(theme: Theme, band: Style) -> Theme:
    """`theme`'s roles measured against `band`'s background, for the words and marks drawn on that band, in its
    launch look (`theme.look`); still without colour when `theme` is (`without_colour`)."""
    skin = theme_for_name(theme.name) or default_theme()
    built = with_launch_look(build_theme(skin, band.bg), skin, band.bg, theme.look)
    return without_colour(built) if theme.text.depth == NO_COLOR else built


def without_colour(theme: Theme) -> Theme:
    """`theme` painted at the `NO_COLOR` depth (no-color.org): every style keeps its bold, dim, italic, underline and
    reverse, and the pager's footer bar (`status`), which only its background told apart, is reversed. A menu's
    highlighted row keeps its pointer and its bold."""

    def plain(value: object) -> object:
        if isinstance(value, Style):
            return replace(value, depth=NO_COLOR)
        if isinstance(value, tuple):
            return tuple(plain(item) for item in value)
        return value

    painted = replace(theme, **{field.name: plain(getattr(theme, field.name)) for field in fields(theme)})
    return replace(painted, status=replace(painted.status, reverse=True))


def theme_named(value: str, background: str | None = None) -> Theme:
    """The theme for a short name (`amber`) or skin name (`omh-amber`), the default for anything else, against `background`."""
    skin = theme_for_name(value) or theme_for_skin_name(value) or default_theme()
    return build_theme(skin, background)


DEFAULT_THEME = build_theme(default_theme())
